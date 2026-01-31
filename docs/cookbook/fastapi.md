# FastAPI Projects

Configure pytest-gremlins for FastAPI applications with async code, dependency injection, and API endpoints.

## Goal

Run mutation testing on FastAPI applications, properly handling async/await patterns, dependency
injection, and Pydantic models.

## Prerequisites

- FastAPI project with pytest and pytest-asyncio configured
- Existing test suite using pytest
- pytest-gremlins installed

## Project Structure

This recipe assumes a typical FastAPI structure:

```text
myapi/
├── src/
│   └── myapi/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── dependencies.py
│       ├── models/
│       │   ├── __init__.py
│       │   └── user.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   └── user.py
│       ├── routers/
│       │   ├── __init__.py
│       │   └── users.py
│       └── services/
│           ├── __init__.py
│           └── user_service.py
├── tests/
│   ├── conftest.py
│   ├── test_routers/
│   │   └── test_users.py
│   └── test_services/
│       └── test_user_service.py
└── pyproject.toml
```

## Steps

1. Install dependencies
2. Configure pytest-asyncio and pytest-gremlins
3. Set up test fixtures for FastAPI
4. Run mutation testing

## Configuration

### Install Dependencies

```bash
pip install pytest-gremlins pytest-asyncio httpx
```

Or with uv:

```bash
uv add pytest-gremlins pytest-asyncio httpx
```

### pyproject.toml

Create or update `pyproject.toml`:

```toml
[project]
name = "myapi"
version = "1.0.0"
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn>=0.27.0",
    "pydantic>=2.0.0",
    "sqlalchemy>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-gremlins>=1.0.0",
    "httpx>=0.26.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra --strict-markers"

[tool.pytest-gremlins]
paths = ["src/myapi"]

exclude = [
    # Pydantic models are mostly declarative
    "**/schemas/*",

    # Config is typically environment-based
    "**/config.py",

    # Main app setup is boilerplate
    "**/main.py",

    # Cache and generated
    "**/__pycache__/*",
]
```

### Test Fixtures

Create `tests/conftest.py`:

```python
"""Pytest configuration for FastAPI mutation testing."""

from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from myapi.main import app
from myapi.dependencies import get_db
from myapi.models import Base


# Test database setup
SQLALCHEMY_DATABASE_URL = 'sqlite:///./test.db'
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={'check_same_thread': False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope='session')
def setup_database():
    """Create test database tables."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(setup_database) -> Generator[Session, None, None]:
    """Create a fresh database session for each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
async def async_client(db_session: Session) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session: Session) -> dict[str, Any]:
    """Create a test user in the database."""
    from myapi.models.user import User

    user = User(
        email='test@example.com',
        hashed_password='fakehash',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    return {
        'id': user.id,
        'email': user.email,
        'is_active': user.is_active,
    }
```

### Example: Service Tests

Create `tests/test_services/test_user_service.py`:

```python
"""Tests for UserService - designed for mutation testing."""

import pytest
from unittest.mock import Mock, AsyncMock

from myapi.services.user_service import UserService
from myapi.schemas.user import UserCreate


class TestUserServiceCreate:
    """Tests for user creation."""

    async def test_create_user_hashes_password(self):
        """Password is hashed before storage."""
        mock_repo = Mock()
        mock_repo.create = AsyncMock(return_value={'id': 1, 'email': 'test@example.com'})
        mock_hasher = Mock()
        mock_hasher.hash = Mock(return_value='hashed_password')

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)
        user_data = UserCreate(email='test@example.com', password='plaintext')

        await service.create_user(user_data)

        mock_hasher.hash.assert_called_once_with('plaintext')

    async def test_create_user_returns_user_without_password(self):
        """Created user response excludes password."""
        mock_repo = Mock()
        mock_repo.create = AsyncMock(return_value={
            'id': 1,
            'email': 'test@example.com',
            'hashed_password': 'secret',
        })
        mock_hasher = Mock()
        mock_hasher.hash = Mock(return_value='hashed')

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)
        user_data = UserCreate(email='test@example.com', password='pass')

        result = await service.create_user(user_data)

        assert 'hashed_password' not in result
        assert 'password' not in result

    async def test_create_user_with_duplicate_email_raises(self):
        """Duplicate email raises ValueError."""
        mock_repo = Mock()
        mock_repo.get_by_email = AsyncMock(return_value={'id': 1})  # User exists
        mock_hasher = Mock()

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)
        user_data = UserCreate(email='existing@example.com', password='pass')

        with pytest.raises(ValueError, match='Email already registered'):
            await service.create_user(user_data)


class TestUserServiceAuthenticate:
    """Tests for user authentication."""

    async def test_authenticate_returns_user_for_valid_credentials(self):
        """Valid credentials return user."""
        mock_repo = Mock()
        mock_repo.get_by_email = AsyncMock(return_value={
            'id': 1,
            'email': 'test@example.com',
            'hashed_password': 'hashed',
            'is_active': True,
        })
        mock_hasher = Mock()
        mock_hasher.verify = Mock(return_value=True)

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)

        result = await service.authenticate('test@example.com', 'password')

        assert result is not None
        assert result['email'] == 'test@example.com'

    async def test_authenticate_returns_none_for_wrong_password(self):
        """Wrong password returns None."""
        mock_repo = Mock()
        mock_repo.get_by_email = AsyncMock(return_value={
            'id': 1,
            'email': 'test@example.com',
            'hashed_password': 'hashed',
            'is_active': True,
        })
        mock_hasher = Mock()
        mock_hasher.verify = Mock(return_value=False)

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)

        result = await service.authenticate('test@example.com', 'wrong')

        assert result is None

    async def test_authenticate_returns_none_for_nonexistent_user(self):
        """Nonexistent user returns None."""
        mock_repo = Mock()
        mock_repo.get_by_email = AsyncMock(return_value=None)
        mock_hasher = Mock()

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)

        result = await service.authenticate('nobody@example.com', 'pass')

        assert result is None

    async def test_authenticate_returns_none_for_inactive_user(self):
        """Inactive user returns None."""
        mock_repo = Mock()
        mock_repo.get_by_email = AsyncMock(return_value={
            'id': 1,
            'email': 'test@example.com',
            'hashed_password': 'hashed',
            'is_active': False,  # Inactive
        })
        mock_hasher = Mock()
        mock_hasher.verify = Mock(return_value=True)

        service = UserService(repository=mock_repo, password_hasher=mock_hasher)

        result = await service.authenticate('test@example.com', 'password')

        assert result is None
```

### Example: Router Tests

Create `tests/test_routers/test_users.py`:

```python
"""Tests for user API endpoints - designed for mutation testing."""

import pytest
from fastapi import status


class TestCreateUser:
    """Tests for POST /users endpoint."""

    def test_create_user_returns_201(self, client):
        """Successful creation returns 201."""
        response = client.post(
            '/users/',
            json={'email': 'new@example.com', 'password': 'securepass123'},
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_create_user_returns_user_data(self, client):
        """Response includes user data."""
        response = client.post(
            '/users/',
            json={'email': 'new@example.com', 'password': 'securepass123'},
        )

        data = response.json()
        assert data['email'] == 'new@example.com'
        assert 'id' in data

    def test_create_user_excludes_password(self, client):
        """Response excludes password."""
        response = client.post(
            '/users/',
            json={'email': 'new@example.com', 'password': 'securepass123'},
        )

        data = response.json()
        assert 'password' not in data
        assert 'hashed_password' not in data

    def test_create_user_invalid_email_returns_422(self, client):
        """Invalid email returns 422."""
        response = client.post(
            '/users/',
            json={'email': 'not-an-email', 'password': 'securepass123'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_user_short_password_returns_422(self, client):
        """Short password returns 422."""
        response = client.post(
            '/users/',
            json={'email': 'new@example.com', 'password': '123'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_duplicate_email_returns_400(self, client, test_user):
        """Duplicate email returns 400."""
        response = client.post(
            '/users/',
            json={'email': test_user['email'], 'password': 'securepass123'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestGetUser:
    """Tests for GET /users/{id} endpoint."""

    def test_get_user_returns_200(self, client, test_user):
        """Existing user returns 200."""
        response = client.get(f"/users/{test_user['id']}")

        assert response.status_code == status.HTTP_200_OK

    def test_get_user_returns_user_data(self, client, test_user):
        """Response includes user data."""
        response = client.get(f"/users/{test_user['id']}")

        data = response.json()
        assert data['email'] == test_user['email']
        assert data['id'] == test_user['id']

    def test_get_nonexistent_user_returns_404(self, client):
        """Nonexistent user returns 404."""
        response = client.get('/users/99999')

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestListUsers:
    """Tests for GET /users endpoint."""

    def test_list_users_returns_200(self, client):
        """List endpoint returns 200."""
        response = client.get('/users/')

        assert response.status_code == status.HTTP_200_OK

    def test_list_users_returns_array(self, client):
        """Response is an array."""
        response = client.get('/users/')

        assert isinstance(response.json(), list)

    def test_list_users_includes_created_user(self, client, test_user):
        """List includes created users."""
        response = client.get('/users/')

        emails = [u['email'] for u in response.json()]
        assert test_user['email'] in emails

    def test_list_users_pagination_limit(self, client):
        """Pagination limit is respected."""
        response = client.get('/users/?limit=5')

        assert len(response.json()) <= 5

    def test_list_users_pagination_offset(self, client, test_user):
        """Pagination offset skips records."""
        # First request without offset
        response1 = client.get('/users/?limit=10')
        all_users = response1.json()

        if len(all_users) > 1:
            # Request with offset should skip first record
            response2 = client.get('/users/?limit=10&offset=1')
            offset_users = response2.json()

            assert len(offset_users) == len(all_users) - 1
```

### Example: Async Tests

For testing async code directly:

```python
"""Tests for async functions."""

import pytest


class TestAsyncOperations:
    """Tests for async operations."""

    async def test_fetch_external_data_returns_result(self):
        """External data fetch returns parsed result."""
        from myapi.services.external import fetch_weather

        # Using mock or test double
        result = await fetch_weather(city='London', api_key='test')

        assert 'temperature' in result
        assert 'conditions' in result

    async def test_batch_process_handles_empty_list(self):
        """Batch processor handles empty input."""
        from myapi.services.batch import process_items

        result = await process_items([])

        assert result == []

    async def test_batch_process_returns_all_results(self):
        """Batch processor returns result for each input."""
        from myapi.services.batch import process_items

        result = await process_items([1, 2, 3])

        assert len(result) == 3
```

## Verification

1. Verify pytest-asyncio works:

   ```bash
   pytest tests/ -v
   ```

2. Run mutation testing:

   ```bash
   pytest --gremlins
   ```

3. Generate HTML report:

   ```bash
   pytest --gremlins --gremlin-report=html
   ```

4. Review surviving gremlins for test gaps

## Troubleshooting

### RuntimeError: Event loop is closed errors

Ensure pytest-asyncio is configured correctly:

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Or use explicit markers:

```python
@pytest.mark.asyncio
async def test_something():
    ...
```

### Database state leaks between mutation test runs

Use transaction rollback fixtures:

```python
@pytest.fixture
def db_session(setup_database):
    """Each test gets a fresh transaction that's rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()
```

### Dependency injection not working in tests

Ensure you override dependencies before creating the test client:

```python
@pytest.fixture
def client(db_session):
    # Override BEFORE creating client
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as c:
        yield c

    # Clean up AFTER client is closed
    app.dependency_overrides.clear()
```

### Slow async tests during mutation testing

Async tests can be slow. Optimize with:

1. Use synchronous TestClient when possible (it handles async internally)

2. Mock external services:

   ```python
   @pytest.fixture
   def mock_external_api(mocker):
       return mocker.patch('myapi.services.external.fetch_data', return_value={'data': 'mocked'})
   ```

3. Run subset of operators:

   ```bash
   pytest --gremlins --gremlin-operators=comparison
   ```

## Pydantic Model Testing

While we exclude schemas from mutation, you can still test validation:

```python
"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError
from myapi.schemas.user import UserCreate


class TestUserCreateSchema:
    """Tests for UserCreate schema validation."""

    def test_valid_user_creates_successfully(self):
        """Valid data creates schema."""
        user = UserCreate(email='test@example.com', password='securepass123')

        assert user.email == 'test@example.com'

    def test_invalid_email_raises_validation_error(self):
        """Invalid email raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(email='not-an-email', password='securepass123')

        assert 'email' in str(exc_info.value)

    def test_short_password_raises_validation_error(self):
        """Short password raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(email='test@example.com', password='123')

        assert 'password' in str(exc_info.value)
```
