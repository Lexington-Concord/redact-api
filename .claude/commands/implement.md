---
description: Implement a backend feature following FastAPI patterns
argument-hint: <feature-description>
---

# Implement Backend Feature

Implement a new feature for this Python FastAPI microservice backend.

## Usage

```bash
/implement <feature-description>
```

## Implementation Workflow

### Phase 1: Analysis (5-10 min)
1. Understand requirements - clarify scope
2. Survey existing patterns - review similar endpoints/services
3. Plan architecture - models, services, API, tests
4. Check dependencies - required libraries available?

### Phase 2: Implementation (30-60 min)
1. **Models** - Pydantic request/response schemas
2. **Database** - SQLAlchemy models if needed
3. **Service** - Business logic in service layer
4. **API** - FastAPI route handlers
5. **Migrations** - Alembic migrations for schema changes
6. **Tests** - Unit + integration tests

### Phase 3: Verification (5-10 min)
```bash
ruff check .     # Must be 0 violations
mypy .           # Must be 0 type errors
pytest           # Must be 100% pass rate
```

## Code Structure

```
app/
├── api/v1/endpoints/
│   └── <resource>.py        # New API routes
├── models/
│   └── <resource>.py        # Pydantic schemas
├── services/
│   └── <resource>_service.py  # Business logic
└── db/models/
    └── <resource>.py        # SQLAlchemy models

tests/
├── unit/services/
│   └── test_<resource>_service.py
└── integration/api/
    └── test_<resource>_endpoints.py
```

## Example Feature Patterns

### Simple CRUD Endpoint

**Pydantic Models:**
```python
# models/product.py
class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., gt=0)

class ProductRead(BaseModel):
    id: int
    name: str
    price: float
    created_at: datetime

    model_config = {"from_attributes": True}
```

**Service:**
```python
# services/product_service.py
class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ProductCreate) -> Product:
        product = Product(**data.model_dump())
        self.db.add(product)
        await self.db.commit()
        await self.db.refresh(product)
        return product
```

**API:**
```python
# api/v1/endpoints/products.py
@router.post("/", response_model=ProductRead, status_code=201)
async def create_product(
    product: ProductCreate,
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    service = ProductService(db)
    return await service.create(product)
```

## Common Mistakes to Avoid

- ❌ Business logic in API routes
- ❌ Sync database calls (use async)
- ❌ Missing type annotations
- ❌ Forgetting `-> None` return type
- ❌ Hardcoded values (use constants)
- ❌ Inline error messages (extract to variables)
- ❌ Missing tests
- ❌ Skipping migration for schema changes

## Definition of Done

- ✅ Ruff: 0 violations
- ✅ MyPy: 0 type errors
- ✅ Pytest: 100% pass rate
- ✅ Coverage: 80%+ on new code
- ✅ Migration created (if schema changed)
- ✅ API documented (OpenAPI)

---

**Before reporting complete:** Run all checks and verify 100% pass rate.
