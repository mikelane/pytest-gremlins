/**
 * Table sorting initialization for MkDocs Material
 * Enables sortable tables throughout documentation
 */
document.addEventListener("DOMContentLoaded", function() {
  // Initialize tablesort on all tables that don't have a class
  const tables = document.querySelectorAll("article table:not([class])");
  tables.forEach(function(table) {
    new Tablesort(table);
  });
});
