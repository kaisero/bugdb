"""Utility functions for the crawler module."""

import logging
import re
from copy import copy
from datetime import datetime, timezone

from bugdb.models import BugDatabase, Metadata, Product

# Configure module logger
logger = logging.getLogger(__name__)

# Base URLs for documentation
BASE_URL = "https://docs.paloaltonetworks.com"
CORTEX_BASE_URL = "https://docs-cortex.paloaltonetworks.com"


def version_sort_key(version: str) -> tuple:
    """Create a sort key for version strings.

    Args:
        version: Version string like "6.2.8-h9" or "6.1.0".

    Returns:
        Tuple for sorting.
    """
    # Split into base version and suffix
    match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-(.+))?", version)
    if match:
        major, minor, patch = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        suffix = match.group(4) or ""
        # Extract numeric part from suffix (e.g., "h9" -> 9, "c471" -> 471)
        suffix_num = 0
        suffix_match = re.search(r"(\d+)", suffix)
        if suffix_match:
            suffix_num = int(suffix_match.group(1))
        return (major, minor, patch, suffix_num)
    return (0, 0, 0, 0)


def get_existing_versions(database: BugDatabase) -> dict[str, set[str]]:
    """Extract existing product versions from a BugDatabase.

    Args:
        database: Existing BugDatabase to extract versions from.

    Returns:
        Dict mapping product IDs to sets of version strings.
        Example: {"globalprotect": {"6.2.1", "6.2.0"}, "panos": {"12.1.5"}}
    """
    result: dict[str, set[str]] = {}
    for product in database.products:
        result[product.id] = {v.version for v in product.versions}
    return result


def merge_databases(existing: BugDatabase, new: BugDatabase) -> BugDatabase:
    """Merge two BugDatabases, combining products and versions.

    New versions are added to existing products. If a product doesn't exist
    in the existing database, it's added entirely. Versions are sorted
    after merging.

    Args:
        existing: The existing database to merge into.
        new: The new database with additional versions.

    Returns:
        A new BugDatabase with merged content.
    """
    # Create a dict of existing products by ID
    products_by_id: dict[str, Product] = {p.id: p for p in existing.products}

    for new_product in new.products:
        if new_product.id in products_by_id:
            # Merge versions into existing product
            existing_product = products_by_id[new_product.id]
            existing_versions = {v.version for v in existing_product.versions}

            # Add new versions that don't already exist
            merged_versions = list(existing_product.versions)
            for new_version in new_product.versions:
                if new_version.version not in existing_versions:
                    merged_versions.append(new_version)

            # Sort versions (newest first)
            merged_versions.sort(
                key=lambda v: version_sort_key(v.version),
                reverse=True,
            )

            # Update the product with merged versions
            products_by_id[new_product.id] = Product(
                id=existing_product.id,
                name=existing_product.name,
                versions=merged_versions,
            )
        else:
            # Add new product entirely
            products_by_id[new_product.id] = new_product

    # Use metadata from existing database but update generated_at
    return BugDatabase(
        metadata=Metadata(
            generated_at=datetime.now(timezone.utc),
            version=existing.metadata.version,
            source=existing.metadata.source,
        ),
        products=list(products_by_id.values()),
    )


def extract_workaround(description: str) -> tuple[str, str | None]:
    """Extract workaround text from an issue description.

    Looks for patterns like "Workaround: <text>" or "Workaround:<text>" in the
    description and extracts the workaround text, returning the cleaned description
    and the workaround separately.

    Args:
        description: The full issue description that may contain a workaround.

    Returns:
        Tuple of (cleaned_description, workaround). If no workaround is found,
        workaround will be None and description is returned unchanged.
    """
    if not description:
        return description, None

    # Pattern to match "Workaround:" followed by text
    # Handles variations like:
    # - "Workaround: text here"
    # - "Workaround:text here"
    # - "WORKAROUND: text here"
    # - Multi-line workarounds (until end of string or next section header)
    pattern = r"(?i)\bworkaround\s*:\s*(.+?)(?=\n(?:[A-Z][a-z]+\s*:|$)|$)"

    match = re.search(pattern, description, re.DOTALL | re.IGNORECASE)

    if match:
        workaround = match.group(1).strip()

        # Remove the workaround section from description
        cleaned_description = description[: match.start()].strip()

        # Also remove any text after the workaround that was captured
        remaining = description[match.end() :].strip()
        if remaining:
            cleaned_description = (
                f"{cleaned_description} {remaining}".strip() if cleaned_description else remaining
            )

        # Replace newlines with spaces and clean up multiple spaces
        cleaned_description = re.sub(r"\s+", " ", cleaned_description).strip()
        workaround = re.sub(r"\s+", " ", workaround).strip()

        # Don't return empty workarounds
        if workaround:
            return cleaned_description, workaround

    return description, None


def extract_fix_info_from_description(
    description: str, existing_fix_info: str | None = None
) -> tuple[str, str | None]:
    """Extract fix information from an issue description.

    Looks for patterns like "This issue is resolved in <version>" in the
    description and extracts it as fix_info. If existing_fix_info is provided
    (e.g., from the bug ID column), it will be reformatted if it matches the
    "This issue is resolved in..." pattern.

    Args:
        description: The issue description that may contain fix information.
        existing_fix_info: Any fix_info already extracted from the bug ID.

    Returns:
        Tuple of (cleaned_description, fix_info). If no fix info is found
        and no existing_fix_info provided, fix_info will be None.
    """
    # Reformat existing_fix_info if it matches the "This issue is resolved in..." pattern
    if existing_fix_info:
        existing_match = re.match(
            r"(?i)^This\s+issue\s+is\s+resolved\s+in\s+(.+?)\.?$", existing_fix_info.strip()
        )
        if existing_match:
            existing_fix_info = f"Resolved in {existing_match.group(1).strip()}"

    if not description:
        return description, existing_fix_info

    # If we already have fix_info from elsewhere, don't extract again
    if existing_fix_info:
        return description, existing_fix_info

    # Pattern to match "This issue is resolved in <version/text>"
    # Handles variations like:
    # - "This issue is resolved in ION 6.3.3."
    # - "This issue is resolved in release 6.5.1."
    # - "This issue is resolved in Prisma SD-WAN ION 6.4.2."
    pattern = r"(?i)\bThis\s+issue\s+is\s+resolved\s+in\s+(.+?)(?:\.(?:\s|$)|$)"

    match = re.search(pattern, description, re.IGNORECASE)

    if match:
        fix_info = match.group(1).strip()

        # Remove the fix info sentence from description
        cleaned_description = description[: match.start()].strip()

        # Add any remaining text after the match
        remaining = description[match.end() :].strip()
        if remaining:
            cleaned_description = (
                f"{cleaned_description} {remaining}".strip() if cleaned_description else remaining
            )

        # Clean up multiple spaces
        cleaned_description = re.sub(r"\s+", " ", cleaned_description).strip()

        # Format the fix_info consistently
        fix_info = f"Resolved in {fix_info}"

        if fix_info and cleaned_description:
            return cleaned_description, fix_info

    return description, existing_fix_info


def extract_bug_id_and_fix_info(raw_bug_id: str) -> tuple[str, str | None]:
    """Extract bug ID and additional fix information from a raw bug ID string.

    Some bug IDs include text like "EPM-4616Resolved in Prisma Access Agent 25.3".
    This function extracts the clean bug ID and any additional fix information.

    Args:
        raw_bug_id: The raw bug ID string that may contain additional text.

    Returns:
        Tuple of (bug_id, fix_info). If no fix info is found, fix_info will be None.
        If the raw string is not a valid bug ID format, returns (raw_bug_id, None).
    """
    if not raw_bug_id:
        return raw_bug_id, None

    # Pattern to extract bug ID (e.g., EPM-4616, PAN-12345) followed by optional text
    match = re.match(r"^([A-Z]+-\d+)(.*)$", raw_bug_id.strip())

    if match:
        bug_id = match.group(1)
        fix_info = match.group(2).strip() if match.group(2) else None

        # Return the cleaned fix_info, or None if empty
        if fix_info:
            return bug_id, fix_info

        return bug_id, None

    return raw_bug_id, None


def extract_affected_components(description: str) -> tuple[str, list[str] | None]:
    """Extract affected components from the start of a description.

    Descriptions may start with parenthesized text like "(NGFW Clusters)" or
    "(PA-5500 Series firewalls only)" indicating affected components/platforms.
    This function extracts those and returns them as a list.

    Args:
        description: The issue description that may start with parenthesized components.

    Returns:
        Tuple of (cleaned_description, affected_components). If no components found,
        affected_components will be None.
    """
    if not description:
        return description, None

    # Pattern to match one or more parenthesized groups at the start
    # Examples: "(NGFW Clusters)", "(PA-5500 Series firewalls only)",
    # "(Different ABC) (Another XYZ)"
    components = []
    cleaned = description.strip()

    # Keep extracting parenthesized text from the start
    while cleaned.startswith("("):
        match = re.match(r"^\(([^)]+)\)\s*", cleaned)
        if match:
            component = match.group(1).strip()
            if component:
                components.append(component)
            cleaned = cleaned[match.end() :].strip()
        else:
            break

    if components:
        return cleaned, components

    return description, None


def normalize_text(element) -> str:
    """Extract text from an HTML element preserving spaces between words.

    Uses separator=' ' to ensure spaces between inline elements like <b>, <i>,
    then collapses multiple spaces into single spaces and strips the result.

    Args:
        element: BeautifulSoup element.

    Returns:
        Normalized text with proper spacing.
    """
    # Use separator to add spaces between text nodes (preserves spaces around <b>, <i>, etc.)
    text = element.get_text(separator=" ")
    # Collapse multiple whitespace characters into single spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def table_to_text(table) -> str:
    """Convert an HTML table element to a plain text representation.

    Args:
        table: BeautifulSoup table element.

    Returns:
        Text representation of the table with rows separated by semicolons
        and cells separated by colons.
    """
    rows = []
    for tr in table.find_all("tr"):
        cells = [normalize_text(cell) for cell in tr.find_all(["td", "th"])]
        if cells:
            rows.append(": ".join(cells))
    return "; ".join(rows)


def extract_cell_text_with_tables(cell) -> str:
    """Extract text from a table cell, converting any nested tables to text.

    Args:
        cell: BeautifulSoup td/th element.

    Returns:
        Text content with nested tables converted to inline text.
    """
    # Clone the cell to avoid modifying the original
    cell_copy = copy(cell)

    # Find all nested tables and replace them with text representation
    nested_tables = cell_copy.find_all("table")
    for nested_table in nested_tables:
        table_text = table_to_text(nested_table)
        nested_table.replace_with(f" [{table_text}] ")

    # Get the text content with proper spacing
    text = normalize_text(cell_copy)
    return text
