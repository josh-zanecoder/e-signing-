from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse, FileResponse
from .models import PDFDocument
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.views.decorators.http import require_http_methods
import json
import base64
from django.core.files.base import ContentFile
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image, ImageEnhance
import io
import os
import fitz  # PyMuPDF

# Create your views here.

@require_http_methods(["GET", "POST"])
def upload_pdf(request):
    if request.method == 'POST':
        if 'pdf_file' in request.FILES:
            try:
                pdf_file = request.FILES['pdf_file']
                document = PDFDocument.objects.create(
                    original_pdf=pdf_file
                )
                # Check if it's an HTMX request
                if request.headers.get('HX-Request'):
                    # Return only the preview section using the same template
                    return render(request, 'pdf_signer/upload.html', {
                        'document': document,
                        'success': True,
                        'message': 'PDF uploaded successfully!'
                    })
                # Regular form submit - return full page
                return render(request, 'pdf_signer/upload.html', {
                    'document': document,
                    'success': True,
                    'message': 'PDF uploaded successfully!'
                })
            except Exception as e:
                return render(request, 'pdf_signer/upload.html', {
                    'error': f'Error uploading PDF: {str(e)}'
                })
        else:
            return render(request, 'pdf_signer/upload.html', {
                'error': 'No PDF file was uploaded'
            })
    
    # GET request - show upload form
    return render(request, 'pdf_signer/upload.html')

@require_http_methods(["GET", "POST"])
def preview_pdf(request, pk):
    document = get_object_or_404(PDFDocument, pk=pk)
    
    # Find <<SIGN HERE>> coordinates when loading the preview
    if document.original_pdf:
        try:
            pdf_document = fitz.open(document.original_pdf.path)
            page = pdf_document[0]  # First page
            text_instances = page.search_for("<<SIGN HERE>>")
            
            if text_instances:
                # Get the position of the signature placeholder
                rect = text_instances[0]
                signature_position = {
                    'x': rect.x0,
                    'y': rect.y0,
                    'width': rect.width,
                    'height': rect.height
                }
                return render(request, 'pdf_signer/preview.html', {
                    'document': document,
                    'signature_position': json.dumps(signature_position)
                })
        except Exception as e:
            print(f"Error finding signature position: {e}")
    
    return render(request, 'pdf_signer/preview.html', {'document': document})


@require_http_methods(["POST"])
def sign_pdf(request, pk):
    try:
        document = get_object_or_404(PDFDocument, pk=pk)
        positions = json.loads(request.POST.get('positions', '[]'))
        
        if not positions:
            return JsonResponse({
                'success': False,
                'error': 'Missing signature data'
            })

        # Open PDF
        pdf_document = fitz.open(document.original_pdf.path)
        
        # Get the preview signature path
        preview_sig_path = os.path.join('media', 'signatures', f'preview_sig_{document.id}.png')
        
        if not os.path.exists(preview_sig_path):
            return JsonResponse({
                'success': False,
                'error': 'Preview signature not found'
            })
            
        # Scale factor to match preview (1.5 is the scale used in PDF.js)
        scale_factor = 1.5
        
        # First, remove all <<SIGN HERE>> instances from all pages
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            text_instances = page.search_for("<<SIGN HERE>>")
            
            # Remove all instances of <<SIGN HERE>> on this page
            for text_rect in text_instances:
                page.draw_rect(text_rect, color=(1, 1, 1), fill=(1, 1, 1))
            
        # Then insert signatures
        for pos in positions:
            page = pdf_document[pos['page'] - 1]
            rect = pos['rect']
            
            # Convert preview coordinates to PDF coordinates (divide by scale)
            signature_rect = fitz.Rect(
                float(rect[0]) / scale_factor,      # x position
                float(rect[1]) / scale_factor,      # y position
                float(rect[2]) / scale_factor,      # right position
                float(rect[3]) / scale_factor       # bottom position
            )
            
            # Insert the exact preview signature image
            try:
                page.insert_image(
                    signature_rect,
                    filename=preview_sig_path,
                    keep_proportion=True,
                    overlay=True
                )
            except Exception as e:
                print(f"Error inserting image: {e}")
                print(f"Rect: {signature_rect}")
                print(f"Image path: {preview_sig_path}")
                raise
        
        # Save the signed PDF with high quality settings
        output_path = f'signed_pdfs/signed_{document.id}.pdf'
        os.makedirs('media/signed_pdfs', exist_ok=True)
        output_full_path = os.path.join('media', output_path)
        
        pdf_document.save(
            output_full_path,
            garbage=4,
            deflate=True,
            clean=True,
            pretty=True
        )
        pdf_document.close()
        
        document.signed_pdf.name = output_path
        document.save()
        
        return JsonResponse({
            'success': True,
            'download_url': document.signed_pdf.url,
            'message': 'Document signed successfully'
        })
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def download_pdf(request, pk):
    document = get_object_or_404(PDFDocument, pk=pk)
    if document.signed_pdf:
        response = FileResponse(
            document.signed_pdf.open('rb'),
            content_type='application/pdf'
        )
        response['Content-Disposition'] = f'attachment; filename="signed_{document.id}.pdf"'
        return response
    return HttpResponse('No signed PDF available', status=404)

@require_http_methods(["POST"])
def preview_signature(request, pk):
    try:
        document = get_object_or_404(PDFDocument, pk=pk)
        
        # Get signature data and position
        signature_data = request.POST.get('signature', '')
        box_x = float(request.POST.get('box_x', 0))
        box_y = float(request.POST.get('box_y', 0))
        box_width = float(request.POST.get('box_width', 200))
        box_height = float(request.POST.get('box_height', 60))
        
        if not signature_data:
            return JsonResponse({
                'success': False,
                'error': 'Missing signature data'
            })

        # Open the PDF to find and remove all <<SIGN HERE>> instances
        pdf_document = fitz.open(document.original_pdf.path)
        
        # Process all pages
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            text_instances = page.search_for("<<SIGN HERE>>")
            
            # Remove all instances of <<SIGN HERE>> on this page
            for text_rect in text_instances:
                page.draw_rect(text_rect, color=(1, 1, 1), fill=(1, 1, 1))
        
        # Save the modified PDF with a unique name
        temp_pdf_path = os.path.join('media', 'pdfs', f'temp_preview_{document.id}.pdf')
        os.makedirs(os.path.dirname(temp_pdf_path), exist_ok=True)
        pdf_document.save(temp_pdf_path)
        pdf_document.close()

        # Process signature image
        format, imgstr = signature_data.split(';base64,')
        signature_bytes = base64.b64decode(imgstr)
        signature_image = Image.open(io.BytesIO(signature_bytes))
        
        if signature_image.mode != 'RGBA':
            signature_image = signature_image.convert('RGBA')
        
        # Make white pixels transparent
        data = signature_image.getdata()
        new_data = []
        for item in data:
            if item[0] > 230 and item[1] > 230 and item[2] > 230:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append((item[0], item[1], item[2], 255))
        
        signature_image.putdata(new_data)

        # Calculate dimensions
        target_height = box_height
        sig_aspect = signature_image.width / signature_image.height
        target_width = int(target_height * sig_aspect)
        
        # Resize signature
        signature_image_resized = signature_image.resize(
            (target_width, int(target_height)), 
            Image.Resampling.LANCZOS
        )

        # Save the signature
        temp_sig_path = f'media/signatures/preview_sig_{document.id}.png'
        os.makedirs('media/signatures', exist_ok=True)
        signature_image_resized.save(temp_sig_path, format='PNG', quality=95)
        
        return JsonResponse({
            'success': True,
            'signature_url': f'/media/signatures/preview_sig_{document.id}.png',
            'pdf_url': f'/media/pdfs/temp_preview_{document.id}.pdf',
            'position': {
                'x': box_x,
                'y': box_y,
                'width': target_width,
                'height': target_height
            }
        })
            
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': str(e)
        })