from sqlalchemy import Column, Integer, String, Text, Boolean, DECIMAL, JSON
from api.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(1000), nullable=False)
    description = Column(Text, nullable=True)
    top_features = Column(JSON, nullable=True)   # array of strings
    category = Column(String(1000), nullable=True)
    is_live = Column(Boolean, default=False)
    is_sellable = Column(Boolean, default=False)
    selling_price = Column(DECIMAL(10, 2), nullable=True)
    original_price = Column(DECIMAL(10, 2), nullable=True)
    discount_percentage = Column(DECIMAL(5, 2), nullable=True)
    retailers = Column(JSON, nullable=True)      # array of retailer objects
