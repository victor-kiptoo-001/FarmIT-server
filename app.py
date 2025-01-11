from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import ee
import logging
from google.oauth2 import service_account
from google.auth.transport.requests import Request

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize logging
logging.basicConfig(level=logging.DEBUG)

# Service account email and credentials file
SERVICE_ACCOUNT_EMAIL = 'gee-analysis@farm-i-t-2k6y4w.iam.gserviceaccount.com'
CREDENTIALS_FILE = './credentials.json'

# Function to initialize or refresh Earth Engine credentials
def initialize_earth_engine():
    try:
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        # Refresh the token if it is expired
        credentials.refresh(Request())
        ee.Initialize(credentials)
        app.logger.info("Earth Engine initialized successfully")
    except Exception as e:
        app.logger.error(f"Failed to initialize Earth Engine: {e}")
        raise

# Function to ensure Earth Engine is initialized and retry failed requests if needed
def ensure_earth_engine_initialized():
    if not ee.data._credentials or ee.data._credentials.expired:
        app.logger.info("Earth Engine credentials expired. Reinitializing...")
        initialize_earth_engine()

# Initialize Earth Engine on startup
initialize_earth_engine()

@app.route('/')
def index():
    return jsonify({"message": "Welcome to the Earth Engine API. Use the /calculate_indices endpoint to perform calculations."})

@app.route('/calculate_indices', methods=['POST'])
def calculate_indices():
    try:
        # Ensure Earth Engine is initialized and credentials are valid
        ensure_earth_engine_initialized()
        
        data = request.json
        if 'coordinates' not in data:
            return jsonify({"error": "No coordinates provided"}), 400
        if 'index' not in data:
            return jsonify({"error": "No index specified"}), 400
        
        geom = ee.Geometry.Polygon(data['coordinates'])
        index = data['index'].upper()

        # Load Sentinel-2 image collection
        collection = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
            .filterDate('2023-06-01', '2023-08-31') \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
            .median()

        # Function to calculate vegetation indices
        def calculate_indices(image):
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            reci = image.normalizedDifference(['B8', 'B5']).rename('RECI')
            ndmi = image.normalizedDifference(['B8', 'B11']).rename('NDMI')

            nir = image.select('B8')
            red = image.select('B4')

            msavi = nir.multiply(2).add(1) \
                .subtract(
                    nir.multiply(2).add(1).pow(2)
                    .subtract(nir.subtract(red).multiply(8))
                    .sqrt()
                ) \
                .divide(2).rename('MSAVI')

            return image.addBands([ndvi, reci, ndmi, msavi])

        # Calculate indices for the given geometry
        indices = calculate_indices(collection).clip(geom)

        # Get the specified index band
        if index == 'NDVI':
            band = indices.select('NDVI')
            palette = ['#8B4513', '#FF0000', '#FFFF00', '#008000']  # Brown, Red, Yellow, Green
            min_value = 0  # Adjusted to 0 to prevent dark/black rendering
            max_value = 1
        elif index == 'RECI':
            band = indices.select('RECI')
            palette = ['#8B0000', '#FFA500', '#FFFF00', '#90EE90', '#006400']  # Dark Red, Orange, Yellow, Light Green, Dark Green
            min_value = 0
            max_value = 5
        elif index == 'NDMI':
            band = indices.select('NDMI')
            palette = ['#3B2C1C', '#FF0000', '#FFFF00', '#90EE90', '#00008B']  # Dark Brown, Red, Yellow, Light Green, Dark Blue
            min_value = -1
            max_value = 1
        elif index == 'MSAVI':
            band = indices.select('MSAVI')
            palette = ['#3B2C1C', '#FF0000', '#FFA500', '#90EE90', '#006400']  # Dark Brown, Red, Orange, Light Green, Dark Green
            min_value = 0  # Adjusted to 0
            max_value = 1
        else:
            return jsonify({"error": "Invalid index specified"}), 400

        # Visualize the selected band
        vis_params = {
            'min': min_value,
            'max': max_value,
            'palette': palette
        }

        # Generate thumbnail URL for the visualization
        url = band.visualize(**vis_params).getThumbURL({
            'region': geom,
            'dimensions': 512,  # Set dimensions for better visibility
            'format': 'png'
        })

        # Log the URL for debugging
        app.logger.debug(f"Generated URL: {url}")

        return jsonify({"url": url, "coordinates": data['coordinates'], "index": index})

    except ee.EEException as e:
        app.logger.error(f"Earth Engine error: {e}")
        # Attempt to refresh the credentials and reinitialize Earth Engine
        try:
            initialize_earth_engine()
            # Retry the failed request after reinitialization
            app.logger.info("Retrying the operation after Earth Engine reinitialization...")
            return calculate_indices()  # Retry the current request
        except Exception as reauth_error:
            return jsonify({"error": f"Failed to reinitialize Earth Engine: {reauth_error}"}), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}")
        return jsonify({"error": "An unexpected error occurred: " + str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # Get the PORT from the environment or default to 5000
    app.run(host='0.0.0.0', port=port, debug=False)  # Bind to 0.0.0.0 to listen on all network interfaces

