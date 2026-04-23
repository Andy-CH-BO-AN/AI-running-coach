from src.ingestion.garmin_client import get_garmin_activities
from src.preprocessing.data_processor import preprocess_data
from agents.coach import coach
import pandas as pd
from datetime import datetime

def run_pipeline():
    """
    Execute the full AI coach pipeline.
    """
    print("Starting Garmin AI Coach Pipeline...")
    
    # Ingestion
    print("Fetching Garmin data...")
    garmin_data = get_garmin_activities()
    raw_activities = garmin_data.get('activities', [])
    user_data = garmin_data.get('user_data', {})
    
    print(f"User profile - Max HR: {user_data.get('max_heart_rate')}, Resting HR: {user_data.get('resting_heart_rate')}")
    
    # Preprocessing
    print("Preprocessing data...")
    processed_data = preprocess_data(raw_activities)
    
    # Analysis
    print("Analyzing data with AI...")
    response = coach(processed_data, user_data)
    
    # Output CSV
    print("Generating CSV output...")
    date_today = datetime.now().strftime('%Y%m%d')
    filename = f'output/ai_analysis_{date_today}.csv'
    df = pd.DataFrame([response])
    df.to_csv(filename, index=False)
    
    print(f"Pipeline completed. Output saved to {filename}")
    return filename