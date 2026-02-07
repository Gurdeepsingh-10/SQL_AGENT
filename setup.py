"""
Quick start script to set up and run the SQL Agent backend.
"""

import os
import sys
from pathlib import Path


def create_env_file():
    """Create .env file from .env.example if it doesn't exist."""
    env_example = Path(".env.example")
    env_file = Path(".env")
    
    if not env_file.exists() and env_example.exists():
        print("📝 Creating .env file from .env.example...")
        env_file.write_text(env_example.read_text())
        print("✅ .env file created. Please update it with your API keys.")
        return False
    return True


def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import fastapi
        import sqlalchemy
        import groq
        return True
    except ImportError:
        print("❌ Dependencies not installed.")
        print("📦 Installing dependencies...")
        os.system(f"{sys.executable} -m pip install -r requirements.txt")
        return True


def initialize_database():
    """Initialize the database."""
    print("🗄️  Initializing database...")
    from app.database import init_db
    init_db()
    print("✅ Database initialized")


def load_example_data():
    """Ask user if they want to load example data."""
    response = input("\n❓ Would you like to load example data? (y/n): ")
    if response.lower() == 'y':
        import sqlite3
        from app.config import settings
        
        if "sqlite" in settings.DATABASE_URL:
            db_path = settings.DATABASE_URL.replace("sqlite:///", "")
            print(f"📊 Loading example data into {db_path}...")
            
            conn = sqlite3.connect(db_path)
            with open("examples/example_schema.sql", "r") as f:
                conn.executescript(f.read())
            conn.close()
            
            print("✅ Example data loaded")
        else:
            print("⚠️  Example data loading only supported for SQLite")


def main():
    """Main setup function."""
    print("=" * 60)
    print("🚀 AI-Powered SQL Agent Backend - Quick Start")
    print("=" * 60)
    
    # Check and create .env file
    env_ready = create_env_file()
    if not env_ready:
        print("\n⚠️  Please update your .env file with:")
        print("   - GROQ_API_KEY")
        print("   - SECRET_KEY (generate a random string)")
        print("\nThen run this script again.")
        return
    
    # Check dependencies
    check_dependencies()
    
    # Initialize database
    try:
        initialize_database()
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        return
    
    # Load example data
    load_example_data()
    
    print("\n" + "=" * 60)
    print("✅ Setup complete!")
    print("=" * 60)
    print("\n📚 Next steps:")
    print("   1. Start the server: uvicorn app.main:app --reload")
    print("   2. Visit API docs: http://localhost:8000/docs")
    print("   3. Register a user via /auth/register")
    print("   4. Login to get JWT token")
    print("   5. Use /agent/query to process natural language queries")
    print("\n💡 See README.md for detailed usage instructions")
    print("=" * 60)


if __name__ == "__main__":
    main()
