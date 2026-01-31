# Django Projects

Configure pytest-gremlins for Django projects with models, views, and Django-specific settings.

## Goal

Run mutation testing on Django applications, handling Django's unique patterns like ORM models, class-based views, and settings configuration.

## Prerequisites

- Django project with pytest-django configured
- Existing test suite using pytest
- pytest-gremlins installed

## Project Structure

This recipe assumes a typical Django structure:

```
myproject/
├── myproject/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── myapp/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   ├── services.py
│   └── migrations/
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_views.py
│   └── test_services.py
├── manage.py
└── pyproject.toml
```

## Steps

1. Install dependencies
2. Configure pytest-django and pytest-gremlins
3. Set up Django test settings
4. Run mutation testing

## Configuration

### Install Dependencies

```bash
pip install pytest-gremlins pytest-django
```

Or with uv:

```bash
uv add pytest-gremlins pytest-django
```

### pyproject.toml

Create or update `pyproject.toml`:

```toml
[project]
name = "myproject"
version = "1.0.0"
dependencies = [
    "django>=4.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-django>=4.5.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "myproject.settings_test"
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-ra --strict-markers"

[tool.pytest-gremlins]
# Only mutate application code, not Django config
paths = [
    "myapp",
]

# Django-specific exclusions
exclude = [
    # Never mutate migrations
    "**/migrations/*",

    # Admin is often boilerplate
    "**/admin.py",

    # App config is boilerplate
    "**/apps.py",

    # URL routing is declarative
    "**/urls.py",

    # Cache and generated files
    "**/__pycache__/*",
]
```

### Django Test Settings

Create `myproject/settings_test.py`:

```python
"""Django settings for testing with pytest-gremlins."""

from myproject.settings import *  # noqa: F401, F403

# Use in-memory SQLite for fast tests
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable password hashing for faster tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Disable logging during tests
LOGGING = {}

# Use fast email backend
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Disable caching
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Disable debug toolbar if installed
DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': lambda request: False,
}
```

### pytest conftest.py

Create `tests/conftest.py`:

```python
"""Pytest configuration for Django mutation testing."""

import pytest


@pytest.fixture(scope='session')
def django_db_setup():
    """Configure database for test session."""
    pass  # Use default setup with in-memory SQLite


@pytest.fixture
def api_client():
    """Create a Django REST framework API client."""
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def authenticated_client(django_user_model, client):
    """Create an authenticated test client."""
    user = django_user_model.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123',
    )
    client.force_login(user)
    return client
```

### Example: Model Tests

Create `tests/test_models.py`:

```python
"""Tests for Django models - designed for mutation testing."""

import pytest
from decimal import Decimal
from myapp.models import Product, Order


@pytest.mark.django_db
class TestProductModel:
    """Tests for Product model."""

    def test_price_must_be_positive(self):
        """Product rejects negative prices."""
        with pytest.raises(ValueError, match='Price must be positive'):
            Product.objects.create(name='Test', price=Decimal('-10.00'))

    def test_discounted_price_applies_percentage(self):
        """Discounted price calculates correctly."""
        product = Product(name='Test', price=Decimal('100.00'))

        result = product.discounted_price(discount_percent=20)

        assert result == Decimal('80.00')

    def test_discounted_price_zero_discount_returns_original(self):
        """Zero discount returns original price."""
        product = Product(name='Test', price=Decimal('100.00'))

        result = product.discounted_price(discount_percent=0)

        assert result == Decimal('100.00')

    def test_discounted_price_hundred_percent_returns_zero(self):
        """100% discount returns zero."""
        product = Product(name='Test', price=Decimal('100.00'))

        result = product.discounted_price(discount_percent=100)

        assert result == Decimal('0.00')


@pytest.mark.django_db
class TestOrderModel:
    """Tests for Order model."""

    def test_total_sums_line_items(self):
        """Order total equals sum of line items."""
        order = Order.objects.create()
        order.add_item(product_name='A', price=Decimal('10.00'), quantity=2)
        order.add_item(product_name='B', price=Decimal('5.00'), quantity=1)

        assert order.total == Decimal('25.00')

    def test_empty_order_total_is_zero(self):
        """Empty order has zero total."""
        order = Order.objects.create()

        assert order.total == Decimal('0.00')

    def test_is_empty_true_for_new_order(self):
        """New order is empty."""
        order = Order.objects.create()

        assert order.is_empty is True

    def test_is_empty_false_after_adding_item(self):
        """Order with items is not empty."""
        order = Order.objects.create()
        order.add_item(product_name='A', price=Decimal('10.00'), quantity=1)

        assert order.is_empty is False
```

### Example: View Tests

Create `tests/test_views.py`:

```python
"""Tests for Django views - designed for mutation testing."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestProductListView:
    """Tests for product list view."""

    def test_returns_200_for_anonymous_user(self, client):
        """Product list is publicly accessible."""
        url = reverse('product-list')

        response = client.get(url)

        assert response.status_code == 200

    def test_context_contains_products(self, client):
        """Product list includes products in context."""
        # Create test data
        from myapp.models import Product
        Product.objects.create(name='Test Product', price='9.99')

        url = reverse('product-list')
        response = client.get(url)

        assert 'products' in response.context
        assert len(response.context['products']) == 1

    def test_empty_list_when_no_products(self, client):
        """Empty list returned when no products exist."""
        url = reverse('product-list')

        response = client.get(url)

        assert list(response.context['products']) == []


@pytest.mark.django_db
class TestProductDetailView:
    """Tests for product detail view."""

    def test_returns_404_for_nonexistent_product(self, client):
        """404 returned for missing product."""
        url = reverse('product-detail', kwargs={'pk': 99999})

        response = client.get(url)

        assert response.status_code == 404

    def test_returns_product_data(self, client):
        """Product detail includes product data."""
        from myapp.models import Product
        product = Product.objects.create(name='Test', price='19.99')

        url = reverse('product-detail', kwargs={'pk': product.pk})
        response = client.get(url)

        assert response.status_code == 200
        assert response.context['product'].name == 'Test'


@pytest.mark.django_db
class TestCheckoutView:
    """Tests for checkout view requiring authentication."""

    def test_redirects_anonymous_user(self, client):
        """Anonymous users redirected to login."""
        url = reverse('checkout')

        response = client.get(url)

        assert response.status_code == 302
        assert '/login/' in response.url

    def test_authenticated_user_can_access(self, authenticated_client):
        """Authenticated users can access checkout."""
        url = reverse('checkout')

        response = authenticated_client.get(url)

        assert response.status_code == 200
```

## Verification

1. Verify pytest-django works:
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

4. Check surviving gremlins for test gaps

## Troubleshooting

**Issue: "No module named 'myproject.settings'" error**

Ensure the Django settings module is correctly configured:

```toml
# pyproject.toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "myproject.settings_test"
```

And verify the settings file exists and is importable:

```bash
python -c "import myproject.settings_test"
```

**Issue: Database errors during mutation testing**

Mutation testing runs tests many times. Ensure database is reset properly:

```python
# tests/conftest.py
@pytest.fixture(autouse=True)
def reset_sequences(db):
    """Reset database sequences after each test."""
    from django.core.management import call_command
    yield
    call_command('flush', '--no-input', verbosity=0)
```

Or use transactional tests:

```python
@pytest.mark.django_db(transaction=True)
def test_something():
    ...
```

**Issue: Mutations in migrations causing failures**

Ensure migrations are excluded:

```toml
[tool.pytest-gremlins]
exclude = [
    "**/migrations/*",
    "**/migrations/**",
]
```

**Issue: Slow mutation testing**

Django tests with database access are slow. Speed up with:

1. Use in-memory SQLite (shown in settings_test.py above)
2. Reduce test database setup:
   ```python
   @pytest.fixture(scope='module')
   def django_db_setup(django_db_blocker):
       with django_db_blocker.unblock():
           # Setup runs once per module
           pass
   ```
3. Run subset of operators first:
   ```bash
   pytest --gremlins --gremlin-operators=comparison,boolean
   ```

## Django REST Framework

For DRF projects, add API-specific test patterns:

```python
# tests/test_api.py
"""Tests for DRF API endpoints."""

import pytest
from rest_framework import status


@pytest.mark.django_db
class TestProductAPI:
    """Tests for Product API."""

    def test_list_returns_all_products(self, api_client):
        """GET /api/products/ returns all products."""
        from myapp.models import Product
        Product.objects.create(name='A', price='10.00')
        Product.objects.create(name='B', price='20.00')

        response = api_client.get('/api/products/')

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    def test_create_requires_authentication(self, api_client):
        """POST /api/products/ requires auth."""
        response = api_client.post('/api/products/', {'name': 'New', 'price': '5.00'})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_with_invalid_price_returns_400(self, authenticated_api_client):
        """Invalid price returns 400."""
        response = authenticated_api_client.post(
            '/api/products/',
            {'name': 'Test', 'price': 'invalid'}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'price' in response.data
```
