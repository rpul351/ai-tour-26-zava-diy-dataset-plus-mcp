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
