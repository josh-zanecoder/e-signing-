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
                # Create new PDFDocument instance
                document = PDFDocument.objects.create(
                    original_pdf=pdf_file
                )
                # Return preview template with the document
                return render(request, 'pdf_signer/preview_snippet.html', {
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
        
        # Get signature data
        signature_data = request.POST.get('signature', '')
        positions = json.loads(request.POST.get('positions', '[]'))
        
        if not signature_data or not positions:
            return JsonResponse({
                'success': False,
                'error': 'Missing signature data'
            })

        # Convert base64 to image
        format, imgstr = signature_data.split(';base64,')
        signature_bytes = base64.b64decode(imgstr)
        signature_image = Image.open(io.BytesIO(signature_bytes))
        
        # Resize signature to a reasonable size (not too big, not too small)
        signature_image = signature_image.resize((400, 150), Image.Resampling.LANCZOS)
        
        # Save signature temporarily
        temp_sig_path = f'media/signatures/temp_sig_{document.id}.png'
        os.makedirs('media/signatures', exist_ok=True)
        signature_image.save(temp_sig_path, quality=95)
        
        # Open PDF
        pdf_document = fitz.open(document.original_pdf.path)
        
        for pos in positions:
            page = pdf_document[pos['page'] - 1]
            
            # Find the exact <<SIGN HERE>> placeholder
            text_instances = page.search_for("<<SIGN HERE>>")
            if text_instances:
                text_rect = text_instances[0]  # Get the first instance
                
                # Create signature rectangle at placeholder position
                signature_rect = fitz.Rect(
                    text_rect.x0,          # Same x position as placeholder
                    text_rect.y0 - 20,     # Slightly above to center
                    text_rect.x0 + 150,    # Reasonable width
                    text_rect.y0 + 50      # Reasonable height
                )
                
                # Remove the <<SIGN HERE>> placeholder
                page.draw_rect(text_rect, color=(1, 1, 1), fill=(1, 1, 1))
                
                # Place signature
                page.insert_image(signature_rect, filename=temp_sig_path, keep_proportion=True)
        
        # Save the signed PDF
        output_path = f'signed_pdfs/signed_{document.id}.pdf'
        os.makedirs('media/signed_pdfs', exist_ok=True)
        output_full_path = os.path.join('media', output_path)
        pdf_document.save(output_full_path)
        pdf_document.close()
        
        # Clean up
        if os.path.exists(temp_sig_path):
            os.remove(temp_sig_path)
        
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
