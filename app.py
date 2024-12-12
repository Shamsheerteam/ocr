import io
import os
import re
import json
import base64
from flask import Flask, request, jsonify
import requests
from google.cloud import vision
from google.cloud import firestore

# Decode and set Google Application Credentials from the Render environment variable
encoded_credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_ENCODED")
if encoded_credentials:
    decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
    with open("service_account.json", "w") as cred_file:
        cred_file.write(decoded_credentials)
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = "service_account.json"

# Initialize Firestore client
project_id = os.getenv('PROJECT_ID')
db = firestore.Client(project=project_id)

app = Flask(__name__)

def detect_text(image_url, document_id):
    """Detects text in the image from the given URL."""
    status = {
        'success': False,
        'message': '',
        'extracted_text': '',
        'processed_data': None,
    }
    
    try:
        response = requests.get(image_url, stream=True)
        response.raise_for_status()

        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=response.content)

        response = client.text_detection(image=image)
        texts = response.text_annotations

        if texts:
            extracted_text = texts[0].description
            status['extracted_text'] = extracted_text

            try:
                text_dict = create_text_dictionary(extracted_text)
                status['processed_data'] = text_dict
                
                # Store in Firestore
                firestore_status = store_in_firestore(text_dict, document_id)
                if firestore_status['success']:
                    status['success'] = True
                    status['message'] = 'Text successfully extracted and stored'
                else:
                    status['message'] = f"Text extracted but storage failed: {firestore_status['message']}"
                
            except ValueError as e:
                status['message'] = f"Error processing text: {str(e)}"
        else:
            status['message'] = 'No text found in image'

        if response.error.message:
            status['message'] = f"Vision API error: {response.error.message}"

    except requests.exceptions.RequestException as e:
        status['message'] = f"Error fetching image from URL: {str(e)}"

    return status

def create_text_dictionary(text):
    """Converts the extracted text to a dictionary."""
    output_dict = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not lines:
        raise ValueError("No text lines found in the input")

    data = lines[4:]
    
    try:
        alternate_dot_pattern = r'^(\d\.)+(\d|\w)$'
        all_digits_pattern = r'^\d+$'
        
        filtered_data = [item for item in data if re.match(alternate_dot_pattern, item) or re.match(all_digits_pattern, item)]
        
        keys = []
        values = []
        for item in filtered_data:
            if any(char.isdigit() for char in item) and any(char == '.' for char in item):
                # Convert the dotted notation to an integer
                # e.g., "1.2.3" becomes 123
                key = int(''.join(filter(str.isdigit, item)))
                keys.append(key)
            elif all(char.isdigit() for char in item):
                values.append(item)
        
        total = len(keys)
        for i in range(0, total):
            output_dict[keys[i]] = values[i]

    except ValueError as e:
        raise ValueError(f"Error processing text format: {str(e)}")

    return output_dict

def store_in_firestore(data_dict, doc_id):
    """Stores the data in a Firestore document, creating it if it doesn't exist."""
    status = {
        'success': False,
        'message': ''
    }
    
    try:
        doc_ref = db.collection('scanned_data').document(doc_id)
        # Add server timestamp to the data
        data_with_timestamp = {
            **data_dict,
            'timestamp': firestore.SERVER_TIMESTAMP
        }
        doc_ref.set(data_with_timestamp, merge=True)
        status['success'] = True
        status['message'] = f"Data stored in Firestore document with ID: {doc_id}"
    except Exception as e:
        status['message'] = f"Error storing data in Firestore: {str(e)}"
    
    return status

@app.route('/process_images', methods=['POST'])
def process_images_api():
    """
    Flask API endpoint to process images from URLs.
    """
    response = {
        'success': False,
        'message': '',
        'results': []
    }
    
    try:
        data = request.get_json()
        image_urls = data.get('image_urls')
        document_id = data.get('document_id')

        if not image_urls or not document_id:
            return jsonify({
                'success': False,
                'message': 'Missing image_urls or document_id'
            }), 400

        for url in image_urls:
            result = detect_text(url, document_id)
            response['results'].append({
                'url': url,
                'status': result
            })
        
        # If at least one image was processed successfully
        if any(result['status']['success'] for result in response['results']):
            response['success'] = True
            response['message'] = 'Processing completed with some successes'
        else:
            response['message'] = 'Processing completed with no successes'
        
        return jsonify(response), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}',
            'results': []
        }), 500

@app.route('/test-api', methods=['POST'])
def test_api():
    """Test API endpoint for POST requests."""
    try:
        data = request.get_json()
        return jsonify({
            'success': True,
            'message': 'Test API received your data successfully!',
            'received_data': data
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
