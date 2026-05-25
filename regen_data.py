import sqlite3
import csv
import random
import os
from datetime import datetime, timedelta

# 1. DELETE OLD SYNTHETIC DATA FROM DB
conn = sqlite3.connect('data/airguard.db')
cursor = conn.cursor()
cursor.execute("DELETE FROM readings WHERE source = 'synthetic'")
conn.commit()

# 2. DELETE OLD SYNTHETIC DATA FROM CSV
csv_path = 'logs/air_readings.csv'
if os.path.exists(csv_path):
    with open(csv_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Keep only lines that don't have 'synthetic' at the end
    clean_lines = [line for line in lines if not line.strip().endswith('synthetic')]
    
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.writelines(clean_lines)

# 3. GET START DATE
cursor.execute('SELECT MIN(ts) FROM readings')
row = cursor.fetchone()
earliest_ts = row[0] if row and row[0] else None

if not earliest_ts:
    earliest_ts = '2026-05-11T00:00:00'

end_date = datetime.fromisoformat(earliest_ts.replace('Z', ''))
start_date = end_date - timedelta(days=30)

# 4. GENERATE NEW DATA (1 reading every 3 minutes)
current_date = start_date
added_count = 0

records_db = []
records_csv = []

while current_date < end_date:
    ts_str = current_date.isoformat()
    adc = random.randint(400, 1500)
    voltage = round(adc * 0.0008, 3)
    aqi = int((voltage - 0.5) * 200)
    if aqi < 0: aqi = 0
    if aqi > 500: aqi = 500
    
    if aqi > 300: label = 'Hazardous'
    elif aqi > 200: label = 'Very Unhealthy'
    elif aqi > 150: label = 'Unhealthy'
    elif aqi > 100: label = 'Unhealthy for Sensitive Groups'
    elif aqi > 50: label = 'Moderate'
    else: label = 'Good'
    
    fan_on = 1 if aqi > 100 else 0
    mode = 'auto'
    threshold_voltage = 1.2
    source = 'synthetic'

    records_db.append((ts_str, adc, voltage, aqi, label, fan_on, mode, threshold_voltage, source))
    records_csv.append([ts_str, adc, voltage, aqi, label, fan_on, mode, threshold_voltage, source])
    
    current_date += timedelta(minutes=3)
    added_count += 1

# 5. INSERT NEW DATA
cursor.executemany('INSERT INTO readings (ts, adc, voltage, aqi, aqi_label, fan_on, mode, threshold_voltage, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', records_db)
conn.commit()
conn.close()

# 6. APPEND TO CSV
with open(csv_path, 'a', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerows(records_csv)

print(f'SUCCESS: Replaced with {added_count} records (1 every 3 minutes).')
