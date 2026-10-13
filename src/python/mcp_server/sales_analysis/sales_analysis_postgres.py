#!/usr/bin/env python3
"""
AI-Friendly PostgreSQL Database Schema Tool

This script provides methods to query PostgreSQL database table schemas in AI-friendly formats
for dynamic query generation and AI model integration.

Usage:
    python sales_data_postgres.py

Requirements:
    - asyncpg (async PostgreSQL adapter)
    - asyncio (for async operations)
    - pandas (for structured JSON output)
    - python-dotenv (for environment variables)
"""

import asyncio
import json
import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import asyncpg
from dotenv import load_dotenv

# Load environment variables (don't override existing ones)
load_dotenv(override=False)

# Configure logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# PostgreSQL connection configuration
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://store_manager:StoreManager123!@db:5432/zava")

SCHEMA_NAME = "retail"
MANAGER_ID = ""

# Constants - table names without schema prefix (will be added in queries)
CUSTOMERS_TABLE = "customers"
PRODUCTS_TABLE = "products"
ORDERS_TABLE = "orders"
ORDER_ITEMS_TABLE = "order_items"
STORES_TABLE = "stores"
CATEGORIES_TABLE = "categories"
PRODUCT_TYPES_TABLE = "product_types"
INVENTORY_TABLE = "inventory"


class PostgreSQLSchemaProvider:
    """Provides PostgreSQL database schema information in AI-friendly formats for dynamic query generation."""

    def __init__(self, postgres_config: Optional[str] = None) -> None:
        self.postgres_config = postgres_config or POSTGRES_URL
        self.connection_pool: Optional[asyncpg.Pool] = None
        self.all_schemas: Optional[Dict[str, Dict[str, Any]]] = None
        # In-memory cache for per-table schema look-ups
        self._schema_cache: Dict[str, Any] = {}

    async def __aenter__(self) -> "PostgreSQLSchemaProvider":
        """Async context manager entry - just return self, don't auto-create pool."""
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[Exception], exc_tb: Optional[object]) -> None:
        """Async context manager exit - close connection pool if it was opened."""
        await self.close_pool()

    async def create_pool(self) -> None:
        """Create connection pool for better resource management."""
        if self.connection_pool is None:
            try:
                self.connection_pool = await asyncpg.create_pool(
                    self.postgres_config,
                    min_size=1,  # Minimum connections in pool
                    max_size=3,  # Very conservative pool size
                    command_timeout=30,  # 30 second query timeout
                    server_settings={
                        "jit": "off",  # Disable JIT to reduce memory usage
                        "work_mem": "4MB",  # Limit work memory per query
                        "statement_timeout": "30s",  # 30 second statement timeout
                    },
                )
                # Don't preload schemas here to avoid connection exhaustion
                logger.info(
                    f"✅ PostgreSQL connection pool created: {self.postgres_config}"
                )
            except Exception as e:
                logger.error(f"❌ Failed to create PostgreSQL pool: {e}")
                raise

    async def ensure_schemas_loaded(self, schema_name: str, rls_user_id:str) -> None:
        """Ensure schemas are loaded for the specified schema, loading them if not already cached."""
        if self.all_schemas is None:
            self.all_schemas = await self.get_all_schemas(schema_name, rls_user_id=rls_user_id)

    async def close_pool(self) -> None:
        """Close connection pool and cleanup."""
        if self.connection_pool:
            await self.connection_pool.close()
            self.connection_pool = None
            self.all_schemas = None
            self._schema_cache = {}
            logger.info("✅ PostgreSQL connection pool closed")

    async def get_connection(self) -> asyncpg.Connection:
        """Get a connection from pool."""
        if not self.connection_pool:
            raise RuntimeError(
                "No database connection pool available. Call create_pool() first.")

        try:
            return await self.connection_pool.acquire()
        except Exception as e:
            logger.error(f"Failed to acquire connection from pool: {e}")
            raise RuntimeError(
                f"Connection pool exhausted or unavailable: {e}") from e

    async def release_connection(self, conn: asyncpg.Connection) -> None:
        """Release connection back to pool."""
        if self.connection_pool:
            await self.connection_pool.release(conn)

    def _parse_table_name(self, table: str) -> tuple[str, str]:
        """Parse table name and return (schema, table_name) tuple. Always assumes table is fully qualified with schema.table format."""
        if "." not in table:
            raise ValueError(
                f"Table name '{table}' must be in 'schema.table' format (e.g., 'retail.customers')")

        parts = table.split(".", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Table name '{table}' must be in 'schema.table' format (e.g., 'retail.customers')")

        schema, table_name = parts
        if not schema or not table_name:
            raise ValueError(
                f"Table name '{table}' must be in 'schema.table' format (e.g., 'retail.customers')")

        return schema, table_name

    def _get_qualified_table_name(self, table: str) -> str:
        """Get fully qualified table name with schema. Expects input to be already qualified."""
        if "." not in table:
            raise ValueError(
                f"Table name '{table}' must be in 'schema.table' format (e.g., 'retail.customers')")

        # Validate the format is correct
        schema, table_name = self._parse_table_name(table)
        return table

    async def table_exists(self, table: str) -> bool:
        """Check if a table exists in the specified schema."""
        conn = None
        try:
            conn = await self.get_connection()
            schema_name, table_name = self._parse_table_name(table)
            result = await conn.fetchval(
                """SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = $1 AND table_name = $2
                )""",
                schema_name,
                table_name,
            )
            return bool(result) if result is not None else False
        except Exception:
            return False
        finally:
            if conn:
                await self.release_connection(conn)

    async def column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in the given table."""
        conn = None
        try:
            conn = await self.get_connection()
            schema_name, table_name = self._parse_table_name(table)
            result = await conn.fetchval(
                """SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_schema = $1 AND table_name = $2 AND column_name = $3
                )""",
                schema_name,
                table_name,
                column,
            )
            return bool(result) if result is not None else False
        except Exception:
            return False
        finally:
            if conn:
                await self.release_connection(conn)

    async def fetch_distinct_values(self, column: str, table: str) -> List[str]:
        """Return sorted list of distinct values for a given column in a table, after validation."""
        schema_name, table_name = self._parse_table_name(table)
        if not await self.table_exists(table):
            raise ValueError(f"Table '{table}' does not exist")
        if not await self.column_exists(table, column):
            raise ValueError(
                f"Column '{column}' does not exist in table '{table}'")

        conn = None
        try:
            conn = await self.get_connection()
            qualified_table = self._get_qualified_table_name(table)
            rows = await conn.fetch(
                f"SELECT DISTINCT {column} FROM {qualified_table} WHERE {column} IS NOT NULL ORDER BY {column}"
            )
            return [row[0] for row in rows if row[0]]
        finally:
            if conn:
                await self.release_connection(conn)

    def infer_relationship_type(self, references_table: str) -> str:
        """Infer a relationship type based on the referenced table."""
        # Extract just the table name without schema for comparison
        try:
            _, table_name = self._parse_table_name(references_table)
        except ValueError:
            # If not in schema.table format, use as-is for comparison
            table_name = references_table

        return (
            "many_to_one"
            if table_name
            in {CUSTOMERS_TABLE, PRODUCTS_TABLE, STORES_TABLE, CATEGORIES_TABLE, PRODUCT_TYPES_TABLE, ORDERS_TABLE}
            else "one_to_many"
        )

    async def get_table_schema(self, table_name: str, rls_user_id: str) -> Dict[str, Any]:
        """Return schema information for a given table."""
        # Return cached version if available
        if table_name in self._schema_cache:
            return self._schema_cache[table_name]

        schema_name, parsed_table_name = self._parse_table_name(table_name)

        if not await self.table_exists(table_name):
            return {"error": f"Table '{table_name}' not found"}

        conn = None
        try:
            conn = await self.get_connection()

            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)", rls_user_id)

            # Get column information
            columns = await conn.fetch(
                """SELECT 
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns 
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position""",
                schema_name,
                parsed_table_name,
            )

            # Get primary key information
            primary_keys = await conn.fetch(
                """SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu 
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = $1 
                    AND tc.table_name = $2""",
                schema_name,
                parsed_table_name,
            )

            pk_columns = {row["column_name"] for row in primary_keys}

            # Get foreign key information
            foreign_keys = await conn.fetch(
                """SELECT 
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu 
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu 
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = $1 
                    AND tc.table_name = $2""",
                schema_name,
                parsed_table_name,
            )

            columns_format = ", ".join(
                f"{col['column_name']}:{col['data_type']}" for col in columns)
            lower_table = parsed_table_name.lower()

            # Define enum queries for each table to get unique values
            enum_queries = {
                STORES_TABLE: {"available_stores": ("store_name", f"{schema_name}.{STORES_TABLE}")},
                CATEGORIES_TABLE: {"available_categories": ("category_name", f"{schema_name}.{CATEGORIES_TABLE}")},
                PRODUCT_TYPES_TABLE: {"available_product_types": ("type_name", f"{schema_name}.{PRODUCT_TYPES_TABLE}")},
                PRODUCTS_TABLE: {
                    # Removed available_product_names to avoid lengthy output
                },
                ORDERS_TABLE: {
                    "available_years": ("EXTRACT(YEAR FROM order_date)::text", f"{schema_name}.{ORDERS_TABLE}")
                },
                ORDER_ITEMS_TABLE: {
                    # "price_range": ("unit_price", f"{schema_name}.{ORDER_ITEMS_TABLE}")
                },
            }

            enum_data = {}
            if lower_table in enum_queries:
                for key, (column, qualified_table) in enum_queries[lower_table].items():
                    try:
                        if key == "price_range":
                            # For price range, get min and max values
                            result = await conn.fetchrow(
                                f"SELECT MIN({column}) as min_price, MAX({column}) as max_price FROM {qualified_table}"
                            )
                            if result and result["min_price"] is not None:
                                enum_data[key] = f"${result['min_price']:.2f} - ${result['max_price']:.2f}"
                        elif key == "available_years":
                            # Handle years specially
                            rows = await conn.fetch(
                                f"SELECT DISTINCT {column} as year FROM {qualified_table} WHERE order_date IS NOT NULL ORDER BY year"
                            )
                            years = [str(row["year"])
                                     for row in rows if row["year"]]
                            enum_data[key] = years
                        else:
                            enum_data[key] = await self.fetch_distinct_values(column, qualified_table)
                    except Exception as e:
                        logger.debug(
                            f"Failed to fetch {key} for {qualified_table}: {e}")
                        enum_data[key] = []

            schema_data = {
                # Keep the original input (may include schema)
                "table_name": table_name,
                "parsed_table_name": parsed_table_name,  # Just the table name
                "schema_name": schema_name,  # The schema name
                "description": f"Table containing {parsed_table_name} data",
                "columns_format": columns_format,
                "columns": [
                    {
                        "name": col["column_name"],
                        "type": col["data_type"],
                        "primary_key": col["column_name"] in pk_columns,
                        "required": col["is_nullable"] == "NO",
                        "default_value": col["column_default"],
                    }
                    for col in columns
                ],
                "foreign_keys": [
                    {
                        "column": fk["column_name"],
                        "references_table": fk["foreign_table_name"],
                        "references_column": fk["foreign_column_name"],
                        "description": f"{fk['column_name']} links to {fk['foreign_table_name']}.{fk['foreign_column_name']}",
                        "relationship_type": self.infer_relationship_type(f"{schema_name}.{fk['foreign_table_name']}"),
                    }
                    for fk in foreign_keys
                ],
            }

            schema_data.update(enum_data)
            # Cache result for future calls
            self._schema_cache[table_name] = schema_data
            return schema_data

        finally:
            if conn:
                await self.release_connection(conn)

    async def get_all_table_names(self, schema_name: str) -> List[str]:
        """Get all user-defined table names in the specified schema."""
        conn = None
        try:
            conn = await self.get_connection()
            rows = await conn.fetch(
                """SELECT table_name FROM information_schema.tables 
                   WHERE table_schema = $1 AND table_type = 'BASE TABLE'
                   ORDER BY table_name""",
                schema_name,
            )
            return [row["table_name"] for row in rows]
        except Exception:
            return []
        finally:
            if conn:
                await self.release_connection(conn)

    async def get_all_schemas(self, schema_name: str, rls_user_id:str) -> Dict[str, Dict[str, Any]]:
        """Get schema metadata for all tables in the specified schema."""
        table_names = await self.get_all_table_names(schema_name)
        result = {}
        for table_name in table_names:
            # Store schema with qualified name using the specified schema
            qualified_name = f"{schema_name}.{table_name}"
            schema_data = await self.get_table_schema(qualified_name, rls_user_id=rls_user_id)
            # Cache by table name only for lookup
            result[table_name] = schema_data
        return result

    def format_schema_metadata_for_ai(self, schema: Dict[str, Any]) -> str:
        """Format schema data into an AI-readable format."""
        if "error" in schema:
            return f"**ERROR:** {schema['error']}"

        # Always use the full schema.table format for display
        # Should already be schema.table format
        table_display = schema.get("table_name")

        # Extract just table name for description
        try:
            _, table_name_only = self._parse_table_name(
                table_display) if table_display else ("", "unknown")
            table_description = table_name_only.replace("_", " ")
        except ValueError:
            table_description = table_display.replace(
                "_", " ") if table_display else "unknown"

        lines = [f"# Table: {table_display}", ""]
        lines.append(
            f"**Purpose:** {schema.get('description', 'No description available')}")
        lines.append("\n## Schema")
        lines.append(schema.get("columns_format", "N/A"))

        if schema.get("foreign_keys"):
            lines.append("\n## Relationships")
            for fk in schema["foreign_keys"]:
                # Use the schema from the current table being processed
                current_schema = schema.get("schema_name")
                if current_schema:
                    fk_table_ref = f"{current_schema}.{fk['references_table']}"
                else:
                    # Fallback to just the table name if no schema available
                    fk_table_ref = fk["references_table"]
                lines.append(
                    f"- `{fk['column']}` → `{fk_table_ref}.{fk['references_column']}` ({fk['relationship_type'].upper()})"
                )

        enum_fields = [
            ("available_stores", "Valid Stores"),
            ("available_categories", "Valid Categories"),
            ("available_product_types", "Valid Product Types"),
            ("available_years", "Available Years"),
            ("price_range", "Price Range"),
        ]

        enum_lines = []
        for field_key, label in enum_fields:
            if schema.get(field_key):
                values = schema[field_key]
                # Always show the full list, no truncation
                enum_lines.append(
                    f"**{label}:** {', '.join(values) if isinstance(values, list) else values}")

        if enum_lines:
            lines.append("\n## Valid Values")
            lines.extend(enum_lines)

        lines.append("\n## Query Hints")
        lines.append(
            f"- Use `{table_display}` for queries about {table_description}")
        if schema.get("foreign_keys"):
            for fk in schema["foreign_keys"]:
                # Use the schema from the current table being processed
                current_schema = schema.get("schema_name")
                if current_schema:
                    fk_table_ref = f"{current_schema}.{fk['references_table']}"
                else:
                    # Fallback to just the table name if no schema available
                    fk_table_ref = fk["references_table"]
                lines.append(
                    f"- Join with `{fk_table_ref}` using `{fk['column']}`")

        return "\n".join(lines) + "\n"

    async def get_table_metadata_string(self, table_name: str, rls_user_id: str) -> str:
        """Return formatted schema metadata string for a single table."""
        # Always get fresh schema data for the specific table
        # This ensures we use the schema from the FQN rather than relying on cached data
        schema = await self.get_table_schema(table_name, rls_user_id=rls_user_id)
        return self.format_schema_metadata_for_ai(schema)

    async def get_table_metadata_from_list(self, table_names: List[str], rls_user_id: str) -> str:
        """Return formatted schema metadata strings for multiple tables efficiently using a single connection."""
        if not table_names:
            return "Error: table_names parameter is required and cannot be empty"

        conn = None
        try:
            conn = await self.get_connection()
            
            # Set rls_user_id once for the connection
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)", rls_user_id)

            schemas = []
            for table_name in table_names:
                try:
                    # Check if table exists first
                    schema_name, parsed_table_name = self._parse_table_name(table_name)
                    table_exists_result = await conn.fetchval(
                        """SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_schema = $1 AND table_name = $2
                        )""",
                        schema_name,
                        parsed_table_name,
                    )
                    
                    if not table_exists_result:
                        schemas.append(f"**ERROR:** Table '{table_name}' not found\n")
                        continue

                    # Get schema data efficiently within the same connection
                    # Use the original method but with our existing connection
                    schema_data = await self._get_table_metadata(conn, table_name)
                    formatted_schema = self.format_schema_metadata_for_ai(schema_data)
                    schemas.append(f"\n\n{formatted_schema}")
                    
                except Exception as e:
                    schemas.append(f"Error retrieving {table_name} schema: {e!s}\n")

            return "".join(schemas)

        finally:
            if conn:
                await self.release_connection(conn)

    async def _get_table_metadata(self, conn: asyncpg.Connection, table_name: str) -> Dict[str, Any]:
        """Get table schema using an existing connection for efficiency."""
        # Return cached version if available
        if table_name in self._schema_cache:
            return self._schema_cache[table_name]

        schema_name, parsed_table_name = self._parse_table_name(table_name)

        # Get column information
        columns = await conn.fetch(
            """SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default,
                ordinal_position
            FROM information_schema.columns 
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position""",
            schema_name,
            parsed_table_name,
        )

        # Get primary key information
        primary_keys = await conn.fetch(
            """SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1 
                AND tc.table_name = $2""",
            schema_name,
            parsed_table_name,
        )

        pk_columns = {row["column_name"] for row in primary_keys}

        # Get foreign key information
        foreign_keys = await conn.fetch(
            """SELECT 
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu 
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = $1 
                AND tc.table_name = $2""",
            schema_name,
            parsed_table_name,
        )

        columns_format = ", ".join(
            f"{col['column_name']}:{col['data_type']}" for col in columns)
        lower_table = parsed_table_name.lower()

        # Define enum queries for each table to get unique values
        enum_queries = {
            STORES_TABLE: {"available_stores": ("store_name", f"{schema_name}.{STORES_TABLE}")},
            CATEGORIES_TABLE: {"available_categories": ("category_name", f"{schema_name}.{CATEGORIES_TABLE}")},
            PRODUCT_TYPES_TABLE: {"available_product_types": ("type_name", f"{schema_name}.{PRODUCT_TYPES_TABLE}")},
            PRODUCTS_TABLE: {
                # Removed available_product_names to avoid lengthy output
            },
            ORDERS_TABLE: {
                "available_years": ("EXTRACT(YEAR FROM order_date)::text", f"{schema_name}.{ORDERS_TABLE}")
            },
            ORDER_ITEMS_TABLE: {
                # "price_range": ("unit_price", f"{schema_name}.{ORDER_ITEMS_TABLE}")
            },
        }

        enum_data = {}
        if lower_table in enum_queries:
            for key, (column, qualified_table) in enum_queries[lower_table].items():
                try:
                    if key == "available_years":
                        # Handle years specially
                        rows = await conn.fetch(
                            f"SELECT DISTINCT {column} as year FROM {qualified_table} WHERE order_date IS NOT NULL ORDER BY year"
                        )
                        years = [str(row["year"])
                                 for row in rows if row["year"]]
                        enum_data[key] = years
                    else:
                        # Use existing connection for fetch_distinct_values-like operation
                        rows = await conn.fetch(
                            f"SELECT DISTINCT {column} FROM {qualified_table} WHERE {column} IS NOT NULL ORDER BY {column}"
                        )
                        enum_data[key] = [row[0] for row in rows if row[0]]
                except Exception as e:
                    logger.debug(
                        f"Failed to fetch {key} for {qualified_table}: {e}")
                    enum_data[key] = []

        schema_data = {
            # Keep the original input (may include schema)
            "table_name": table_name,
            "parsed_table_name": parsed_table_name,  # Just the table name
            "schema_name": schema_name,  # The schema name
            "description": f"Table containing {parsed_table_name} data",
            "columns_format": columns_format,
            "columns": [
                {
                    "name": col["column_name"],
                    "type": col["data_type"],
                    "primary_key": col["column_name"] in pk_columns,
                    "required": col["is_nullable"] == "NO",
                    "default_value": col["column_default"],
                }
                for col in columns
            ],
            "foreign_keys": [
                {
                    "column": fk["column_name"],
                    "references_table": fk["foreign_table_name"],
                    "references_column": fk["foreign_column_name"],
                    "description": f"{fk['column_name']} links to {fk['foreign_table_name']}.{fk['foreign_column_name']}",
                    "relationship_type": self.infer_relationship_type(f"{schema_name}.{fk['foreign_table_name']}"),
                }
                for fk in foreign_keys
            ],
        }

        schema_data.update(enum_data)
        # Cache result for future calls
        self._schema_cache[table_name] = schema_data
        return schema_data

    async def execute_query(self, sql_query: str, rls_user_id: str) -> str:
        """Execute a SQL query and return results in LLM-friendly JSON format."""
        conn = None
        try:
            conn = await self.get_connection()

            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)", rls_user_id)

            # logger.info(f"\n🔍 Executing PostgreSQL query: {sql_query}\n")
            rows = await conn.fetch(sql_query)

            if not rows:
                return json.dumps(
                    {
                        "results": [],
                        "row_count": 0,
                        "columns": [],
                        "message": "The query returned no results. Try a different question.",
                    }
                )

            # Convert asyncpg Records to list of dictionaries (much simpler!)
            results = [dict(row) for row in rows]
            columns = list(rows[0].keys()) if rows else []

            # Return LLM-friendly format
            return json.dumps(
                {"results": results, "row_count": len(results), "columns": columns}, indent=2, default=str
            )

        except Exception as e:
            return json.dumps(
                {
                    "error": f"PostgreSQL query failed: {e!s}",
                    "query": sql_query,
                    "results": [],
                    "row_count": 0,
                    "columns": [],
                }
            )
        finally:
            if conn:
                await self.release_connection(conn)

    async def get_inventory_optimization_overview(
        self,
        rls_user_id: str,
        store_id: Optional[int] = None,
        days_window: int = 30,
        warning_days: int = 7,
        danger_days: int = 3,
    ) -> str:
        """Return stock health for products and stores with recent sales context."""
        conn = None
        try:
            conn = await self.get_connection()
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)",
                rls_user_id,
            )

            sql = """
                WITH recent_sales AS (
                    SELECT
                        oi.product_id,
                        oi.store_id,
                        SUM(oi.quantity)::numeric AS sold_units,
                        (SUM(oi.quantity)::numeric / GREATEST($1::int, 1)) AS avg_daily_units
                    FROM retail.order_items oi
                    JOIN retail.orders o ON o.order_id = oi.order_id
                    WHERE o.order_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')
                    GROUP BY oi.product_id, oi.store_id
                ),
                inventory_snapshot AS (
                    SELECT
                        i.store_id,
                        i.product_id,
                        i.stock_level,
                        s.store_name,
                        p.product_name,
                        c.category_name,
                        COALESCE(rs.sold_units, 0) AS sold_units,
                        COALESCE(rs.avg_daily_units, 0) AS avg_daily_units
                    FROM retail.inventory i
                    JOIN retail.stores s ON s.store_id = i.store_id
                    JOIN retail.products p ON p.product_id = i.product_id
                    JOIN retail.categories c ON c.category_id = p.category_id
                    LEFT JOIN recent_sales rs ON rs.product_id = i.product_id AND rs.store_id = i.store_id
                    WHERE ($2::int IS NULL OR i.store_id = $2)
                )
                SELECT
                    store_id,
                    store_name,
                    product_id,
                    product_name,
                    category_name,
                    stock_level,
                    sold_units,
                    avg_daily_units,
                    CASE
                        WHEN avg_daily_units > 0 THEN stock_level / NULLIF(avg_daily_units, 0)
                        ELSE NULL
                    END AS days_of_cover,
                    CASE
                        WHEN avg_daily_units > 0 AND stock_level <= ($3::int * avg_daily_units) THEN 'critical'
                        WHEN avg_daily_units > 0 AND stock_level <= ($4::int * avg_daily_units) THEN 'warning'
                        WHEN avg_daily_units > 0 AND stock_level > ($4::int * avg_daily_units) THEN 'healthy'
                        ELSE 'unknown'
                    END AS risk_status,
                    CASE
                        WHEN avg_daily_units > 0 THEN stock_level - ($4::int * avg_daily_units)
                        ELSE stock_level
                    END AS stock_gap_vs_safe_level
                FROM inventory_snapshot
                ORDER BY risk_status DESC, days_of_cover ASC, stock_level ASC
                LIMIT 200
            """

            rows = await conn.fetch(
                sql,
                days_window,
                store_id,
                danger_days,
                warning_days,
            )

            if not rows:
                return json.dumps(
                    {
                        "results": [],
                        "row_count": 0,
                        "columns": [
                            "store_id",
                            "store_name",
                            "product_id",
                            "product_name",
                            "category_name",
                            "stock_level",
                            "sold_units",
                            "avg_daily_units",
                            "days_of_cover",
                            "risk_status",
                            "stock_gap_vs_safe_level",
                        ],
                        "message": "No inventory rows found for the requested scope.",
                    },
                    indent=2,
                    default=str,
                )

            results = [dict(row) for row in rows]
            columns = list(rows[0].keys())
            return json.dumps({"results": results, "row_count": len(results), "columns": columns}, indent=2, default=str)
        except Exception as e:
            return json.dumps(
                {
                    "error": f"Inventory optimization overview failed: {e!s}",
                    "results": [],
                    "row_count": 0,
                    "columns": [],
                },
                indent=2,
                default=str,
            )
        finally:
            if conn:
                await self.release_connection(conn)

    async def recommend_inventory_transfers(
        self,
        rls_user_id: str,
        store_id: Optional[int] = None,
        days_window: int = 30,
        critical_days: int = 7,
        surplus_days: int = 21,
    ) -> str:
        """Recommend transfer opportunities from surplus stock to shortage risk locations."""
        conn = None
        try:
            conn = await self.get_connection()
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)",
                rls_user_id,
            )

            sql = """
                WITH recent_sales AS (
                    SELECT
                        oi.product_id,
                        oi.store_id,
                        SUM(oi.quantity)::numeric AS sold_units,
                        (SUM(oi.quantity)::numeric / GREATEST($1::int, 1)) AS avg_daily_units
                    FROM retail.order_items oi
                    JOIN retail.orders o ON o.order_id = oi.order_id
                    WHERE o.order_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')
                    GROUP BY oi.product_id, oi.store_id
                ),
                inventory_health AS (
                    SELECT
                        i.store_id,
                        i.product_id,
                        i.stock_level,
                        s.store_name,
                        p.product_name,
                        c.category_name,
                        COALESCE(rs.avg_daily_units, 0) AS avg_daily_units,
                        CASE
                            WHEN COALESCE(rs.avg_daily_units, 0) > 0 THEN i.stock_level / NULLIF(rs.avg_daily_units, 0)
                            ELSE NULL
                        END AS days_of_cover,
                        CASE
                            WHEN COALESCE(rs.avg_daily_units, 0) > 0 THEN GREATEST(ROUND($2::int * rs.avg_daily_units, 0), 1)
                            ELSE 0
                        END AS safe_stock_level
                    FROM retail.inventory i
                    JOIN retail.stores s ON s.store_id = i.store_id
                    JOIN retail.products p ON p.product_id = i.product_id
                    JOIN retail.categories c ON c.category_id = p.category_id
                    LEFT JOIN recent_sales rs ON rs.product_id = i.product_id AND rs.store_id = i.store_id
                    WHERE ($3::int IS NULL OR i.store_id = $3)
                )
                SELECT
                    surplus.store_name AS surplus_store,
                    shortage.store_name AS shortage_store,
                    shortage.product_id,
                    shortage.product_name,
                    shortage.category_name,
                    surplus.stock_level AS surplus_stock_level,
                    shortage.stock_level AS shortage_stock_level,
                    shortage.avg_daily_units,
                    shortage.days_of_cover AS shortage_days_of_cover,
                    LEAST(
                        GREATEST(surplus.stock_level - surplus.safe_stock_level, 0),
                        GREATEST(shortage.safe_stock_level - shortage.stock_level, 0)
                    ) AS recommended_transfer_units,
                    CASE
                        WHEN shortage.days_of_cover <= 3 THEN 'high'
                        WHEN shortage.days_of_cover <= 7 THEN 'medium'
                        ELSE 'low'
                    END AS priority
                FROM inventory_health AS surplus
                JOIN inventory_health AS shortage
                  ON surplus.product_id = shortage.product_id
                WHERE surplus.store_id <> shortage.store_id
                  AND surplus.stock_level > surplus.safe_stock_level
                  AND shortage.avg_daily_units > 0
                  AND shortage.stock_level < shortage.safe_stock_level
                  AND (shortage.days_of_cover IS NULL OR shortage.days_of_cover <= $4::int)
                  AND (surplus.days_of_cover IS NULL OR surplus.days_of_cover >= $5::int)
                ORDER BY
                    CASE
                        WHEN shortage.days_of_cover <= 3 THEN 1
                        WHEN shortage.days_of_cover <= 7 THEN 2
                        ELSE 3
                    END,
                    recommended_transfer_units DESC
                LIMIT 200
            """

            rows = await conn.fetch(
                sql,
                days_window,
                critical_days,
                store_id,
                critical_days,
                surplus_days,
            )

            if not rows:
                return json.dumps(
                    {
                        "results": [],
                        "row_count": 0,
                        "columns": [
                            "surplus_store",
                            "shortage_store",
                            "product_id",
                            "product_name",
                            "category_name",
                            "surplus_stock_level",
                            "shortage_stock_level",
                            "avg_daily_units",
                            "shortage_days_of_cover",
                            "recommended_transfer_units",
                            "priority",
                        ],
                        "message": "No transfer opportunities were found for the requested scope.",
                    },
                    indent=2,
                    default=str,
                )

            results = [dict(row) for row in rows]
            columns = list(rows[0].keys())
            return json.dumps({"results": results, "row_count": len(results), "columns": columns}, indent=2, default=str)
        except Exception as e:
            return json.dumps(
                {
                    "error": f"Inventory transfer recommendation failed: {e!s}",
                    "results": [],
                    "row_count": 0,
                    "columns": [],
                },
                indent=2,
                default=str,
            )
        finally:
            if conn:
                await self.release_connection(conn)

    async def rank_capital_tied_up(
        self,
        rls_user_id: str,
        store_id: Optional[int] = None,
        window_days: int = 365,
        target_months_cover: int = 6,
        top_n: int = 20,
    ) -> str:
        """Rank products by the cost value of stock held beyond a target months of cover."""
        conn = None
        try:
            conn = await self.get_connection()
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)",
                rls_user_id,
            )
            scope = await self._describe_scope(conn, store_id)

            # Window ends today so future-dated orders never count as sales.
            sql = """
                WITH sales AS (
                    SELECT oi.product_id, SUM(oi.quantity)::numeric AS sold_units
                    FROM retail.order_items oi
                    JOIN retail.orders o ON o.order_id = oi.order_id
                    WHERE o.order_date > CURRENT_DATE - $1::int
                      AND o.order_date <= CURRENT_DATE
                      AND ($2::int IS NULL OR oi.store_id = $2)
                    GROUP BY oi.product_id
                ),
                stock AS (
                    SELECT i.product_id, SUM(i.stock_level)::numeric AS stock_units
                    FROM retail.inventory i
                    WHERE ($2::int IS NULL OR i.store_id = $2)
                    GROUP BY i.product_id
                ),
                metrics AS (
                    SELECT
                        p.product_id,
                        p.product_name,
                        c.category_name,
                        p.cost,
                        st.stock_units,
                        COALESCE(s.sold_units, 0) AS units_sold_in_window,
                        COALESCE(s.sold_units, 0) / ($1::numeric / 30.4375) AS units_per_month
                    FROM stock st
                    JOIN retail.products p ON p.product_id = st.product_id
                    JOIN retail.categories c ON c.category_id = p.category_id
                    LEFT JOIN sales s ON s.product_id = st.product_id
                ),
                scored AS (
                    SELECT
                        m.*,
                        GREATEST(m.stock_units - CEIL(m.units_per_month * $3::int), 0) AS excess_units
                    FROM metrics m
                )
                SELECT
                    product_id,
                    product_name,
                    category_name,
                    stock_units,
                    ROUND(stock_units * cost, 2) AS stock_value,
                    units_sold_in_window,
                    CASE WHEN units_per_month > 0 THEN ROUND(stock_units / units_per_month, 1) END AS months_of_cover,
                    excess_units,
                    ROUND(excess_units * cost, 2) AS excess_value,
                    ROUND(100 * excess_units * cost / NULLIF(SUM(excess_units * cost) OVER (), 0), 2)
                        AS share_of_total_excess_pct,
                    ROUND(SUM(excess_units * cost) OVER (), 2) AS total_excess_value_in_scope,
                    SUM(stock_units) OVER () AS total_stock_units_in_scope,
                    ROUND(SUM(stock_units * cost) OVER (), 2) AS total_stock_value_in_scope
                FROM scored
                ORDER BY excess_value DESC, product_id
                LIMIT $4::int
            """

            rows = await conn.fetch(sql, window_days, store_id, target_months_cover, top_n)
            window_end = await conn.fetchval("SELECT CURRENT_DATE")
            parameters = {
                "store_id": store_id,
                "window_days": window_days,
                "window_end": window_end,
                "target_months_cover": target_months_cover,
                "top_n": top_n,
            }

            if not rows:
                return json.dumps(
                    {
                        "results": [],
                        "row_count": 0,
                        "columns": [],
                        "parameters": parameters,
                        "scope": scope,
                        "message": "No inventory rows found for this scope.",
                    },
                    indent=2,
                    default=str,
                )

            results = [dict(row) for row in rows]
            today = await conn.fetchval("SELECT CURRENT_DATE")
            profiles: Dict[str, Optional[Dict[str, Any]]] = {}
            for result in results:
                name = result["category_name"]
                if name not in profiles:
                    category_id = await conn.fetchval(
                        "SELECT category_id FROM retail.categories WHERE category_name = $1", name
                    )
                    profiles[name] = await self._seasonal_profile(conn, category_id, store_id, today)
                profile = profiles[name]
                if profile is None:
                    result.update(
                        peak_month=None,
                        months_until_peak=None,
                        peak_is_near=None,
                        clearance_guard="unknown: not enough sales history to find this category's seasonal peak",
                    )
                else:
                    near = profile["months_until_peak"] <= 3
                    result.update(
                        peak_month=profile["peak_month"],
                        months_until_peak=profile["months_until_peak"],
                        peak_is_near=near,
                        clearance_guard=(
                            "do not clear: the category's seasonal peak is near"
                            if near
                            else "clearing is not blocked by seasonality"
                        ),
                    )
            columns = list(rows[0].keys()) + ["peak_month", "months_until_peak", "peak_is_near", "clearance_guard"]
            return json.dumps(
                {
                    "results": results,
                    "row_count": len(results),
                    "columns": columns,
                    "parameters": parameters,
                    "scope": scope,
                    "notes": [
                        "Values are at cost. They are an upper bound on the cash released by clearing, not the cash itself.",
                        "Stock levels are a snapshot and are not tied to sales history, so excess is within this dataset.",
                        "clearance_guard comes from the product's category seasonal peak. Do not recommend clearing when it says do not clear.",
                    ],
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps(
                {
                    "error": f"Capital tied up ranking failed: {e!s}",
                    "results": [],
                    "row_count": 0,
                    "columns": [],
                },
                indent=2,
                default=str,
            )
        finally:
            if conn:
                await self.release_connection(conn)

    async def _describe_scope(self, conn: asyncpg.Connection, store_id: Optional[int]) -> Dict[str, Any]:
        """Say which stores the current RLS user can see, so totals are never mistaken for the network."""
        rows = await conn.fetch(
            """
            SELECT DISTINCT s.store_id, s.store_name
            FROM retail.inventory i
            JOIN retail.stores s ON s.store_id = i.store_id
            WHERE ($1::int IS NULL OR i.store_id = $1)
            ORDER BY s.store_id
            """,
            store_id,
        )
        names = [r["store_name"] for r in rows]
        total = await conn.fetchval("SELECT COUNT(*) FROM retail.stores")
        return {
            "stores_included": names,
            "store_count": len(names),
            "covers_all_stores": len(names) == total,
            "note": "These figures cover only the stores listed. They are network totals only when covers_all_stores is true.",
        }

    async def compare_store_coverage(
        self,
        rls_user_id: str,
        category_name: Optional[str] = None,
        window_days: int = 365,
    ) -> str:
        """Compare each store's stock with its share of demand, per category."""
        conn = None
        try:
            conn = await self.get_connection()
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)",
                rls_user_id,
            )
            scope = await self._describe_scope(conn, None)

            # Stock and sales are aggregated separately before joining, so neither is repeated per order line.
            sql = """
                WITH stock AS (
                    SELECT i.store_id, p.category_id,
                           SUM(i.stock_level)::numeric AS stock_units,
                           SUM(i.stock_level * p.cost) AS stock_value
                    FROM retail.inventory i
                    JOIN retail.products p ON p.product_id = i.product_id
                    GROUP BY i.store_id, p.category_id
                ),
                sales AS (
                    SELECT oi.store_id, p.category_id, SUM(oi.quantity)::numeric AS sold_units
                    FROM retail.order_items oi
                    JOIN retail.orders o ON o.order_id = oi.order_id
                    JOIN retail.products p ON p.product_id = oi.product_id
                    WHERE o.order_date > CURRENT_DATE - $1::int
                      AND o.order_date <= CURRENT_DATE
                    GROUP BY oi.store_id, p.category_id
                ),
                joined AS (
                    SELECT st.store_id, st.category_id, st.stock_units, st.stock_value,
                           COALESCE(sa.sold_units, 0) AS sold_units
                    FROM stock st
                    LEFT JOIN sales sa ON sa.store_id = st.store_id AND sa.category_id = st.category_id
                ),
                totals AS (
                    SELECT j.*,
                           SUM(j.stock_units) OVER (PARTITION BY j.category_id) AS category_stock,
                           SUM(j.sold_units) OVER (PARTITION BY j.category_id) AS category_sold
                    FROM joined j
                )
                SELECT
                    s.store_name,
                    c.category_name,
                    t.stock_units,
                    ROUND(t.stock_value, 2) AS stock_value,
                    t.sold_units AS units_sold_in_window,
                    CASE WHEN t.sold_units > 0
                         THEN ROUND(t.stock_units / (t.sold_units / ($1::numeric / 30.4375)), 1) END AS months_of_cover,
                    ROUND(100 * t.stock_units / NULLIF(t.category_stock, 0), 1) AS share_of_stock_pct,
                    ROUND(100 * t.sold_units / NULLIF(t.category_sold, 0), 1) AS share_of_sales_pct,
                    ROUND(t.stock_units - t.category_stock * t.sold_units / NULLIF(t.category_sold, 0))
                        AS units_over_equal_cover
                FROM totals t
                JOIN retail.stores s ON s.store_id = t.store_id
                JOIN retail.categories c ON c.category_id = t.category_id
                WHERE ($2::text IS NULL OR UPPER(c.category_name) = UPPER($2::text))
                ORDER BY c.category_name, units_over_equal_cover DESC NULLS LAST
                LIMIT 200
            """
            rows = await conn.fetch(sql, window_days, category_name)
            parameters = {
                "category_name": category_name,
                "window_days": window_days,
                "window_end": await conn.fetchval("SELECT CURRENT_DATE"),
            }

            if not rows:
                valid = [r["category_name"] for r in await conn.fetch("SELECT category_name FROM retail.categories ORDER BY 1")]
                return json.dumps(
                    {
                        "results": [],
                        "row_count": 0,
                        "parameters": parameters,
                        "scope": scope,
                        "message": "No rows found. Check the category name against the valid list.",
                        "valid_categories": valid,
                    },
                    indent=2,
                    default=str,
                )

            notes = [
                "units_over_equal_cover is stock above what this store would hold if every store had the same months of cover for the category. Negative means below. This is a relative imbalance, not a shortage.",
                "Transfer costs are not in the data.",
            ]
            if scope["store_count"] < 2:
                notes.append("Only one store is visible to this user, so there is nothing to compare against other stores.")
            return json.dumps(
                {
                    "results": [dict(r) for r in rows],
                    "row_count": len(rows),
                    "columns": list(rows[0].keys()),
                    "parameters": parameters,
                    "scope": scope,
                    "notes": notes,
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps(
                {"error": f"Store coverage comparison failed: {e!s}", "results": [], "row_count": 0},
                indent=2,
                default=str,
            )
        finally:
            if conn:
                await self.release_connection(conn)

    async def seasonal_baseline_check(
        self,
        rls_user_id: str,
        category_name: str,
        store_id: Optional[int] = None,
        recent_months: int = 6,
    ) -> str:
        """Give a category's seasonal pattern, when its peak is, and how recent months compare with it."""
        conn = None
        try:
            conn = await self.get_connection()
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)",
                rls_user_id,
            )
            scope = await self._describe_scope(conn, store_id)

            category = await conn.fetchrow(
                "SELECT category_id, category_name FROM retail.categories WHERE UPPER(category_name) = UPPER($1::text)",
                category_name,
            )
            if category is None:
                valid = [r["category_name"] for r in await conn.fetch("SELECT category_name FROM retail.categories ORDER BY 1")]
                return json.dumps(
                    {"results": [], "scope": scope, "message": "Unknown category.", "valid_categories": valid},
                    indent=2,
                    default=str,
                )

            # Complete months only: the current month and future-dated orders are excluded.
            today = await conn.fetchval("SELECT CURRENT_DATE")
            profile = await self._seasonal_profile(conn, category["category_id"], store_id, today)
            if profile is None:
                return json.dumps(
                    {
                        "results": [],
                        "category": category["category_name"],
                        "scope": scope,
                        "message": "Fewer than 2 complete calendar years of history in this scope, so no seasonal pattern is reported.",
                    },
                    indent=2,
                    default=str,
                )
            monthly, complete_years = profile["monthly"], profile["complete_years"]
            index, level_year, level = profile["index"], profile["level_year"], profile["level"]
            peak_month, months_until_peak = profile["peak_month"], profile["months_until_peak"]

            recent = []
            for month_start in sorted(monthly, reverse=True)[:recent_months]:
                expected = index[month_start.month] * level
                actual = monthly[month_start]
                recent.append(
                    {
                        "month": month_start.strftime("%Y-%m"),
                        "actual_units": round(actual),
                        "expected_units": round(expected),
                        "deviation_pct": round(100 * (actual / expected - 1), 1) if expected > 0 else None,
                    }
                )
            recent.reverse()

            return json.dumps(
                {
                    "category": category["category_name"],
                    "scope": scope,
                    "as_of": today,
                    "baseline": {
                        "complete_years_used": complete_years,
                        "level_year": level_year,
                        "level_avg_monthly_units": round(level, 1),
                    },
                    "seasonal_index_by_month": {str(k): round(v, 3) for k, v in index.items()},
                    "peak_month": peak_month,
                    "months_until_peak": months_until_peak,
                    "peak_is_near": months_until_peak <= 3,
                    "recent_months": recent,
                    "notes": [
                        "Index 1.0 means an average month. Expected units = index x average monthly units in the level year.",
                        "Recent months compare against last complete year's level, so a general growth or decline also shows as deviation.",
                        "Lead times are not in the data.",
                    ],
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps(
                {"error": f"Seasonal baseline check failed: {e!s}", "results": [], "row_count": 0},
                indent=2,
                default=str,
            )
        finally:
            if conn:
                await self.release_connection(conn)

    async def _seasonal_profile(
        self, conn: asyncpg.Connection, category_id: int, store_id: Optional[int], today: date
    ) -> Optional[Dict[str, Any]]:
        """Seasonal index and peak for a category from complete months; None with under 2 complete years."""
        rows = await conn.fetch(
            """
            SELECT date_trunc('month', o.order_date)::date AS month_start,
                   SUM(oi.quantity)::numeric AS units
            FROM retail.order_items oi
            JOIN retail.orders o ON o.order_id = oi.order_id
            JOIN retail.products p ON p.product_id = oi.product_id
            WHERE p.category_id = $1
              AND o.order_date < date_trunc('month', CURRENT_DATE)
              AND ($2::int IS NULL OR oi.store_id = $2)
            GROUP BY 1
            ORDER BY 1
            """,
            category_id,
            store_id,
        )
        monthly = {r["month_start"]: float(r["units"]) for r in rows}
        by_year: Dict[int, List[float]] = {}
        for month_start, units in monthly.items():
            by_year.setdefault(month_start.year, []).append(units)
        complete_years = sorted(y for y, v in by_year.items() if len(v) == 12 and y < today.year)
        if len(complete_years) < 2:
            return None

        year_avg = {y: sum(by_year[y]) / 12 for y in complete_years}
        index: Dict[int, float] = {}
        for month_num in range(1, 13):
            ratios = [
                monthly[m] / year_avg[m.year]
                for m in monthly
                if m.month == month_num and m.year in year_avg and year_avg[m.year] > 0
            ]
            index[month_num] = sum(ratios) / len(ratios) if ratios else 0.0

        peak_month = max(index, key=lambda k: index[k])
        return {
            "monthly": monthly,
            "complete_years": complete_years,
            "level_year": complete_years[-1],
            "level": year_avg[complete_years[-1]],
            "index": index,
            "peak_month": peak_month,
            "months_until_peak": (peak_month - today.month) % 12,
        }

    @staticmethod
    def _movers(rows: List[Dict[str, Any]], label_key: str) -> Dict[str, Any]:
        """Largest unit decline and gain, by amount and by percentage, so small and large movers both show."""
        usable = [r for r in rows if r.get("units_change_pct") is not None]
        if not usable:
            return {}

        def entry(row: Dict[str, Any], sign: int) -> Optional[Dict[str, Any]]:
            if row["units_change"] * sign <= 0:
                return None
            return {"name": row[label_key], "units_change": row["units_change"], "units_change_pct": row["units_change_pct"]}

        return {
            "largest_decline_units": entry(min(usable, key=lambda r: r["units_change"]), -1),
            "largest_decline_pct": entry(min(usable, key=lambda r: r["units_change_pct"]), -1),
            "largest_gain_units": entry(max(usable, key=lambda r: r["units_change"]), 1),
            "largest_gain_pct": entry(max(usable, key=lambda r: r["units_change_pct"]), 1),
        }

    @staticmethod
    def _plain(value: Any) -> Any:
        return float(value) if isinstance(value, Decimal) else value

    @staticmethod
    def _period_end(year: int, today: date, partial: bool) -> date:
        if not partial:
            return date(year, 12, 31)
        try:
            return date(year, today.month, today.day)
        except ValueError:  # 29 February in a non-leap year
            return date(year, 2, 28)

    def _with_change(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: self._plain(v) for k, v in row.items()}
        for metric in ("units", "revenue", "orders", "customers"):
            if metric in out and f"{metric}_compare" in out:
                now, before = out[metric] or 0, out[f"{metric}_compare"] or 0
                out[metric], out[f"{metric}_compare"] = now, before
                out[f"{metric}_change"] = round(now - before, 2)
                out[f"{metric}_change_pct"] = round(100 * (now - before) / before, 1) if before else None
        return out

    async def year_over_year_summary(
        self,
        rls_user_id: str,
        year: int,
        compare_year: Optional[int] = None,
    ) -> str:
        """Compare one calendar year with another by total, store, category and calendar month."""
        conn = None
        try:
            conn = await self.get_connection()
            await conn.execute(
                "SELECT set_config('app.current_rls_user_id', $1, false)",
                rls_user_id,
            )
            scope = await self._describe_scope(conn, None)
            today = await conn.fetchval("SELECT CURRENT_DATE")
            compare_year = compare_year if compare_year is not None else year - 1

            if year == compare_year:
                return json.dumps({"error": "year and compare_year must be different."}, indent=2)
            if max(year, compare_year) > today.year:
                return json.dumps(
                    {"message": f"No data for years after {today.year}. Orders dated after today are excluded.", "scope": scope},
                    indent=2,
                )

            # If either year is the current one, both cover the same part of the year.
            partial = today.year in (year, compare_year)
            a_start, a_end = date(year, 1, 1), self._period_end(year, today, partial)
            b_start, b_end = date(compare_year, 1, 1), self._period_end(compare_year, today, partial)
            args = (a_start, a_end, b_start, b_end)

            def pair(agg: str, alias: str, digits: Optional[int] = None) -> str:
                def one(start: str, end: str) -> str:
                    term = f"COALESCE({agg} FILTER (WHERE o.order_date BETWEEN {start} AND {end}), 0)"
                    return f"ROUND({term}, {digits})" if digits is not None else term

                return f"{one('$1', '$2')} AS {alias}, {one('$3', '$4')} AS {alias}_compare"

            measures = ", ".join(
                [
                    pair("SUM(oi.quantity)", "units"),
                    pair("SUM(oi.total_amount)", "revenue", 2),
                    pair("COUNT(DISTINCT o.order_id)", "orders"),
                ]
            )
            source = "FROM retail.order_items oi JOIN retail.orders o ON o.order_id = oi.order_id"
            window = "WHERE o.order_date BETWEEN LEAST($1::date, $3::date) AND GREATEST($2::date, $4::date)"

            totals_row = await conn.fetchrow(
                f"SELECT {measures}, {pair('COUNT(DISTINCT o.customer_id)', 'customers')} {source} {window}", *args
            )
            by_store = await conn.fetch(
                f"SELECT s.store_name, {measures} {source} JOIN retail.stores s ON s.store_id = oi.store_id "
                f"{window} GROUP BY s.store_name ORDER BY units DESC, s.store_name",
                *args,
            )
            by_category = await conn.fetch(
                f"SELECT c.category_name, {measures} {source} "
                f"JOIN retail.products p ON p.product_id = oi.product_id "
                f"JOIN retail.categories c ON c.category_id = p.category_id "
                f"{window} GROUP BY c.category_name ORDER BY units DESC, c.category_name",
                *args,
            )
            # Months are paired by calendar month number so January is compared with January.
            by_month = await conn.fetch(
                f"SELECT EXTRACT(MONTH FROM o.order_date)::int AS month_num, {measures} {source} {window} "
                f"GROUP BY 1 ORDER BY 1",
                *args,
            )

            totals = self._with_change(dict(totals_row))
            store_rows = [self._with_change(dict(r)) for r in by_store]
            category_rows = [self._with_change(dict(r)) for r in by_category]
            month_rows = [self._with_change(dict(r)) for r in by_month]
            if not totals["units"] and not totals["units_compare"]:
                first, last = await conn.fetchrow(
                    "SELECT MIN(order_date), MAX(order_date) FROM retail.orders WHERE order_date <= CURRENT_DATE"
                )
                return json.dumps(
                    {
                        "message": "No orders in either period for this scope.",
                        "orders_available_from": first,
                        "orders_available_to": last,
                        "scope": scope,
                    },
                    indent=2,
                    default=str,
                )

            notes = [
                "Orders dated after today are excluded.",
                "Month rows pair the same calendar month in each year.",
                "The data holds no reasons for a change (promotions, pricing, outages, assortment).",
            ]
            if partial:
                notes.append(
                    f"A year in this comparison is incomplete, so both years cover 1 January to {today.strftime('%d %B')}."
                )
            return json.dumps(
                {
                    "year": year,
                    "compare_year": compare_year,
                    "periods": {
                        str(year): [a_start, a_end],
                        str(compare_year): [b_start, b_end],
                    },
                    "partial_period": partial,
                    "scope": scope,
                    "totals": totals,
                    "by_store": store_rows,
                    "by_category": category_rows,
                    "by_month": month_rows,
                    "biggest_movers": {
                        "by_store": self._movers(store_rows, "store_name"),
                        "by_category": self._movers(category_rows, "category_name"),
                        "by_month": self._movers(month_rows, "month_num"),
                    },
                    "notes": notes,
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps(
                {"error": f"Year over year summary failed: {e!s}", "results": [], "row_count": 0},
                indent=2,
                default=str,
            )
        finally:
            if conn:
                await self.release_connection(conn)


async def test_connection() -> bool:
    """Test PostgreSQL connection and return success status."""
    try:
        # Create a temporary pool for testing
        pool = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=1)
        conn = await pool.acquire()
        await pool.release(conn)
        await pool.close()
        return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False


async def main() -> None:
    """Main function to run the schema tool."""
    logger.info("🤖 AI-Friendly PostgreSQL Database Schema Tool")
    logger.info("=" * 50)

    # Test connection first
    if not await test_connection():
        logger.error(
            f"❌ Error: Cannot connect to PostgreSQL using: {POSTGRES_URL}")
        logger.error("   Please verify:")
        logger.error("   1. PostgreSQL is running")
        logger.error("   2. Database 'zava' exists")
        logger.error("   3. POSTGRES_URL environment variable is correct")
        logger.error("   4. User has access to the retail schema")
        return

    try:
        async with PostgreSQLSchemaProvider() as provider:
            # Create connection pool (schemas will be loaded lazily when needed)
            await provider.create_pool()

            # Preload schemas for testing
            await provider.ensure_schemas_loaded(SCHEMA_NAME, rls_user_id=MANAGER_ID)

            logger.info(
                f"\n📋 Getting all table schemas from {SCHEMA_NAME} schema...")
            if not provider.all_schemas:
                logger.warning(
                    f"❌ No schemas available in {SCHEMA_NAME} schema")
                logger.warning(
                    "   Please run the PostgreSQL database generator first:")
                logger.warning(
                    "   python shared/data/database/generate_zava_postgres.py")
                return

            logger.info("\n🧪 Testing SQL Query Execution:")
            logger.info("=" * 50)

            logger.info("\n📊 Test 1: Count all customers")
            result = await provider.execute_query(f"SELECT COUNT(*) as total_customers FROM {SCHEMA_NAME}.customers", rls_user_id=MANAGER_ID)
            logger.info(f"Result: {result}")

            logger.info("\n📊 Test 2: Count stores")
            result = await provider.execute_query(f"SELECT COUNT(*) as total_stores FROM {SCHEMA_NAME}.stores", rls_user_id=MANAGER_ID)
            logger.info(f"Result: {result}")

            logger.info("\n📊 Test 3: Count categories and types")
            result = await provider.execute_query(f"SELECT COUNT(*) as total_categories FROM {SCHEMA_NAME}.categories", rls_user_id=MANAGER_ID)
            logger.info(f"Result: {result}")

            logger.info("\n📊 Test 4: Orders with revenue")
            result = await provider.execute_query(
                f"""SELECT COUNT(DISTINCT o.order_id) as orders, 
                    SUM(oi.total_amount) as revenue 
                    FROM {SCHEMA_NAME}.orders o 
                    JOIN {SCHEMA_NAME}.order_items oi ON o.order_id = oi.order_id 
                    LIMIT 1""", rls_user_id=MANAGER_ID
            )
            logger.info(f"Result: {result}")

            logger.info("\n✅ SQL Query tests completed!")
            logger.info("=" * 50)
            print(f"\n📋 All table schemas in {SCHEMA_NAME} schema:\n")

            # --- Use the new efficient method for getting all schemas ---
            all_table_names = [
                f"{SCHEMA_NAME}.{STORES_TABLE}",
                f"{SCHEMA_NAME}.{CATEGORIES_TABLE}",
                f"{SCHEMA_NAME}.{PRODUCT_TYPES_TABLE}",
                f"{SCHEMA_NAME}.{PRODUCTS_TABLE}",
                f"{SCHEMA_NAME}.{CUSTOMERS_TABLE}",
                f"{SCHEMA_NAME}.{ORDERS_TABLE}",
                f"{SCHEMA_NAME}.{ORDER_ITEMS_TABLE}",
                f"{SCHEMA_NAME}.{INVENTORY_TABLE}"
            ]
            print(await provider.get_table_metadata_from_list(all_table_names, rls_user_id=MANAGER_ID))

    except Exception as e:
        logger.error(f"❌ Error during analysis: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
