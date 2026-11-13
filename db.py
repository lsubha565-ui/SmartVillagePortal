import mysql.connector
from mysql.connector import Error

# Database Configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '1234',  # Replace with your actual MySQL password
    'database': 'smart_village_db'
}

def get_db_connection():
    """Helper function to create and return a MySQL database connection."""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

if __name__ == '__main__':
    # Test Connection
    conn = get_db_connection()
    if conn:
        print("Success: Connected to MySQL database 'smart_village_db' successfully!")
        conn.close()
    else:
        print("Failed: Could not connect to MySQL database.")