# Database Setup - MariaDB with SQLAlchemy

This directory contains the basic MariaDB SQLAlchemy setup for the PlayLS backend.

## Files Structure

```
database/
├── __init__.py          # Package initialization
├── config.py            # Database configuration and connection
├── models.py            # SQLAlchemy models (User, Rotation)
├── services.py          # Database service layer
├── init_db.py           # Database initialization script
├── example_routes.py    # Example FastAPI routes using the database
└── README.md           # This file
```

## Setup Instructions

### 1. Install Dependencies

The required packages should be in your `requirements.txt`:
- `sqlalchemy==2.0.23` - ORM framework
- `pymysql==1.1.0` - MySQL/MariaDB driver
- `cryptography==41.0.7` - Required for secure connections

Install them:
```bash
pip install -r requirements.txt
```

### 2. Database Configuration

1. Make sure your `env` file has the database settings:
```env
DB_HOST=localhost
DB_PORT=3307
DB_NAME=playls_db
DB_USER=appuser
DB_PASSWORD=mariadb1234
```

2. Make sure you have MariaDB installed and running
3. Create the database: `CREATE DATABASE playls_db;`

### 3. Initialize Database Tables

Run the initialization script:
```bash
cd back-end
python -m rest_api.database.init_db
```

### 4. Using the Database in Your Routes

Example usage:
```python
from fastapi import Depends
from sqlalchemy.orm import Session
from rest_api.database.config import get_db
from rest_api.database.services import UserService

@app.get("/users/{spotify_id}")
async def get_user(spotify_id: str, db: Session = Depends(get_db)):
    user = UserService.get_user_by_spotify_id(db, spotify_id)
    return user
```

## Models

### User Model
- Stores user information including Spotify ID, tokens, and profile data
- One-to-many relationship with Rotation

### Rotation Model
- Stores playlist rotation configurations
- Belongs to a User (many-to-one relationship)

## Services

The service layer provides clean methods for database operations:
- `UserService` - User CRUD operations
- `RotationService` - Rotation CRUD operations

## Next Steps

1. Make sure MariaDB is running
2. Run the database initialization script
3. Start integrating the database services into your existing routes
4. Consider adding data validation with Pydantic schemas
5. Add database migrations for production use (Alembic)

## Production Considerations

- Use connection pooling (already configured)
- Add proper error handling
- Implement database migrations with Alembic
- Use environment-specific configurations
- Add proper logging
- Consider using database constraints and indexes