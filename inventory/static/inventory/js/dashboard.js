// Dashboard page: three Chart.js charts plus the DataTables product table
// with type/location filters and a print summary. All server data arrives
// via json_script blocks (see dashboard.html) and is read with jd() on load.

document.addEventListener('DOMContentLoaded', function () {
  // Helper: read json_script data by element id.
  function jd(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }

  var categoryPalette = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc948', '#b07aa1', '#ff9da7'];

  // -- Charts ---------------------------------------------------------------
  if (typeof Chart !== 'undefined') {
    // Chart 1 — Inventory by Product Type
    new Chart(document.getElementById('categoryChart'), {
      type: 'pie',
      data: {
        labels: jd('type-labels'),
        datasets: [{
          data: jd('type-data'),
          backgroundColor: categoryPalette,
          borderWidth: 1
        }]
      },
      options: { responsive: true, plugins: { legend: { position: 'bottom' }, title: { display: true, text: 'By Product Type' } } }
    });

    // Chart 2 — Filament by Material
    new Chart(document.getElementById('filamentPieChart'), {
      type: 'pie',
      data: {
        labels: jd('filament-labels'),
        datasets: [{ data: jd('filament-data'), backgroundColor: categoryPalette, hoverOffset: 4 }]
      },
      options: { responsive: true, plugins: { legend: { position: 'bottom' }, title: { display: true, text: 'Filament by Material' } } }
    });

    // Chart 3 — Filament by Color Family (real hex colors)
    new Chart(document.getElementById('colorFamilyChart'), {
      type: 'doughnut',
      data: {
        labels: jd('color-labels'),
        datasets: [{
          data: jd('color-data'),
          backgroundColor: jd('color-colors'),
          borderColor: 'rgba(0,0,0,0.15)',
          borderWidth: 1,
          hoverOffset: 6
        }]
      },
      options: { responsive: true, plugins: { legend: { position: 'bottom' }, title: { display: true, text: 'Filament by Color Family' } } }
    });
  }

  // -- Product table (DataTables) ------------------------------------------
  if (typeof $ === 'undefined') {
    console.error('jQuery not loaded - DataTables will not work.');
    return;
  }

  var table = $('#inventoryTable').DataTable({
    ordering: true,
    pageLength: 25,
    order: [[3, 'desc']]  // Sort by Inventory Count, descending
  });

  function updateVisibleTotal() {
    var total = 0;
    table.column(3, { search: 'applied' }).nodes().each(function (cell) {
      var val = parseInt($(cell).text());
      if (!isNaN(val)) total += val;
    });
    $('#totalVisibleCount').text(total);
    $('#visibleCount').text(table.rows({ search: 'applied' }).count());
  }

  function updatePrintSummary(total) {
    var now = new Date();
    document.getElementById('printDate').textContent = now.toLocaleDateString();
    document.getElementById('printVisibleCount').textContent = total;
  }

  $('#typeFilter').on('change', function () {
    table.column(1).search(this.value).draw();
  });
  $('#locationFilter').on('change', function () {
    table.column(3).search(this.value).draw();
  });
  $('#resetFilters').on('click', function () {
    $('#typeFilter').val('');
    $('#locationFilter').val('');
    table.columns().search('').draw();
  });

  table.on('draw', function () {
    updateVisibleTotal();
    updatePrintSummary(table.rows({ search: 'applied' }).count());
  });

  updateVisibleTotal(); // initial
});
