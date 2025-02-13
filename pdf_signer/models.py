from django.db import models
from django.urls import reverse

# Create your models here.

class PDFDocument(models.Model):
    original_pdf = models.FileField(upload_to='original_pdfs/')
    signed_pdf = models.FileField(upload_to='signed_pdfs/', null=True, blank=True)
    upload_date = models.DateTimeField(auto_now_add=True)
    signature_placeholder_found = models.BooleanField(default=False)
    
    def __str__(self):
        return f"PDF Document {self.id} - {self.upload_date}"
    
    def get_preview_url(self):
        return reverse('pdf_signer:preview', kwargs={'pk': self.pk})
    
    def get_sign_url(self):
        return reverse('pdf_signer:sign', kwargs={'pk': self.pk})
