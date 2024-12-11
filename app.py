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
project_id = os.getenv('PROJECT_ID')  # Set your project ID as an environment variable
db = firestore.Client(project=project_id)

app = Flask(__name__)

def detect_text(image_url):
    """Detects text in the image from the given URL and returns the extracted text."""
    try:
        response = requests.get(image_url, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes

        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=response.content)

        response = client.text_detection(image=image)
        texts = response.text_annotations

        if texts:
            return texts[0].description  # Return the detected text from the first annotation
        else:
            print(f"No text found in image: {image_url}")
            return None

        if response.error.message:
            raise Exception(
                '{}\nFor more info on error messages, check: '
                'https://cloud.google.com/apis/design/errors'.format(
                    response.error.message))

    except requests.exceptions.RequestException as e:
        print(f"Error fetching image from URL: {e}")
        return None

def create_text_dictionary(text):
    """Converts the extracted text to a dictionary."""
    text_dict = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not lines:
        raise ValueError("No text lines found in the input")

    for line in lines:
        match = re.match(r"^\s*([\w.]+)\s*,\s*(\d+)\s*$", line)
        if match:
            key, value = match.groups()
            text_dict[key] = int(value)
        else:
            print(f"Ignoring line '{line}' as it doesn't match the 'key,value' format.")

    return text_dict

def store_in_firestore(data_dict, doc_id):
    """Stores the data in a Firestore document, creating it if it doesn't exist."""
    try:
        doc_ref = db.collection('scanned_data').document(doc_id)

        # Merge the data into the existing Firestore document
        doc_ref.set(data_dict, merge=True)
        print(f"Data stored in Firestore document with ID: {doc_id}")

    except Exception as e:
        print(f"Error storing data in Firestore: {e}")

@app.route('/process_images', methods=['POST'])
def process_images_api():
    """
    Flask API endpoint to process images from URLs.

    Expects a JSON payload with the following structure:
    {
        "image_urls": ["url1", "url2", ...],
        "document_id": "your_document_id"
    }
    """
    try:
        data = request.get_json()
        image_urls = data.get('image_urls')
        document_id = data.get('document_id')

        if not image_urls or not document_id:
            return jsonify({'error': 'Missing image_urls or document_id'}), 400

        consolidated_data = {}

        for image_url in image_urls:
            print(f"Processing image: {image_url}")
            try:
                extracted_text = detect_text(image_url)
                if extracted_text:
                    text_dict = create_text_dictionary(extracted_text)
                    consolidated_data.update(text_dict)  # Merge dictionaries
            except Exception as e:
                print(f"Error processing image {image_url}: {e}")

        if not consolidated_data:
            return jsonify({'error': 'No valid text found in the provided images'}), 400

        store_in_firestore(consolidated_data, document_id)

        return jsonify({'message': 'Images processed and data uploaded successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/test-api', methods=['POST'])
def test_api():
    """
    Test API endpoint for POST requests.
    Accepts a JSON payload and echoes it back for debugging purposes.
    """
    try:
        data = request.get_json()
        return jsonify({
            'message': 'Test API received your data successfully!',
            'received_data': data
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
