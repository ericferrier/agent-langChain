from dotenv import load_dotenv
load_dotenv()

from app.db import get_connection  # adjust import path to match your project

try:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM DUAL")
    print("✅ Connection successful!", cursor.fetchone())
    conn.close()
except Exception as e:
    print("❌ Connection failed:", e)