// Filament summary page: client-side material/family/subtype filtering,
// usage-period toggle, swatch overflow, and DataTables init.
//
// Functions referenced by inline onclick attributes in
// filament_summary.html (setPeriod, toggleOverflow) must stay global,
// so they are declared at top level here (a plain <script src> shares
// global scope). All server data arrives via data-* attributes in the
// rendered table/cards; nothing is interpolated into this file.

var activeMaterial = null;
var activeFamily = null;
var activeSubtype = null;
var activePeriod = '7d';

function filterByMaterial(material) {
  if (activeMaterial === material && activeFamily === null) {
    activeMaterial = null;
  } else {
    activeMaterial = material;
    activeFamily = null;
  }
  applyFilters();
}

function filterByFamily(material, family) {
  if (activeMaterial === material && activeFamily === family) {
    activeMaterial = null;
    activeFamily = null;
  } else {
    activeMaterial = material;
    activeFamily = family;
  }
  applyFilters();
}

function clearFilters() {
  activeMaterial = null;
  activeFamily = null;
  activeSubtype = null;
  applyFilters();
}

function clearMaterial() {
  activeMaterial = null;
  activeFamily = null;
  applyFilters();
}

function clearFamily() {
  activeFamily = null;
  applyFilters();
}

function clearSubtype() {
  activeSubtype = null;
  applyFilters();
}

function applyFilters() {
  var rows = document.querySelectorAll('#filament-summary-table tbody tr');
  var visible = 0;
  rows.forEach(function(row) {
    var mat = row.dataset.material;
    var fam = row.dataset.family;
    var sub = row.dataset.subtype;
    var show = (!activeMaterial || mat === activeMaterial) &&
               (!activeFamily || fam === activeFamily) &&
               (!activeSubtype || sub === activeSubtype);
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });

  // Card active state
  document.querySelectorAll('.filament-card').forEach(function(card) {
    card.classList.toggle('border-primary', card.dataset.material === activeMaterial);
    card.classList.toggle('bg-light', card.dataset.material === activeMaterial);
  });

  var matSel = document.getElementById('filter-material');
  if (matSel) matSel.value = activeMaterial || '';
  var famSel = document.getElementById('filter-family');
  if (famSel) famSel.value = activeFamily || '';
  var subSel = document.getElementById('filter-subtype');
  if (subSel) subSel.value = activeSubtype || '';

  // Filter chips
  var chipsEl = document.getElementById('active-filter-chips');
  chipsEl.innerHTML = '';
  if (activeMaterial) {
    var badge = document.createElement('span');
    badge.className = 'badge bg-primary me-1';
    badge.textContent = activeMaterial + ' ';
    var x = document.createElement('span');
    x.style.cursor = 'pointer';
    x.textContent = '✕';
    x.addEventListener('click', function(e) { e.stopPropagation(); clearMaterial(); });
    badge.appendChild(x);
    chipsEl.appendChild(badge);
  }
  if (activeFamily) {
    var badge2 = document.createElement('span');
    badge2.className = 'badge bg-secondary me-1';
    badge2.textContent = activeFamily + ' ';
    var x2 = document.createElement('span');
    x2.style.cursor = 'pointer';
    x2.textContent = '✕';
    x2.addEventListener('click', function(e) { e.stopPropagation(); clearFamily(); });
    badge2.appendChild(x2);
    chipsEl.appendChild(badge2);
  }
  if (activeSubtype) {
    var badge3 = document.createElement('span');
    badge3.className = 'badge bg-info text-dark me-1';
    badge3.textContent = activeSubtype + ' ';
    var x3 = document.createElement('span');
    x3.style.cursor = 'pointer';
    x3.textContent = '✕';
    x3.addEventListener('click', function(e) { e.stopPropagation(); clearSubtype(); });
    badge3.appendChild(x3);
    chipsEl.appendChild(badge3);
  }
  if (activeMaterial || activeFamily || activeSubtype) {
    var clearBtn = document.createElement('button');
    clearBtn.className = 'btn btn-link btn-sm p-0';
    clearBtn.textContent = 'Clear all';
    clearBtn.addEventListener('click', clearFilters);
    chipsEl.appendChild(clearBtn);
  }

  document.getElementById('row-count-label').textContent = visible + ' row' + (visible !== 1 ? 's' : '');
}

function applyPeriodDisplay() {
  var attrMap = {'7d': 'used-7d', '30d': 'used-30d', '1y': 'used-365d'};
  var attr = attrMap[activePeriod];
  document.querySelectorAll('.usage-cell').forEach(function(cell) {
    var raw = parseInt(cell.getAttribute('data-' + attr) || '0', 10);
    cell.textContent = raw > 0 ? raw : '—';
  });
}

function setPeriod(btn) {
  activePeriod = btn.dataset.period;
  document.querySelectorAll('.period-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  btn.classList.add('active');
  applyPeriodDisplay();
  document.getElementById('period-label').textContent = activePeriod;
}

function toggleOverflow(btn) {
  var container = btn.closest('.swatch-container');
  var hidden = container.querySelectorAll('.swatch-hidden');
  var isExpanded = btn.dataset.expanded === 'true';
  if (isExpanded) {
    hidden.forEach(function(s) { s.style.display = 'none'; });
    btn.textContent = '+' + btn.dataset.extra + ' more';
    btn.dataset.expanded = 'false';
  } else {
    hidden.forEach(function(s) { s.style.display = 'inline-block'; });
    btn.textContent = 'show less';
    btn.dataset.expanded = 'true';
  }
}

document.addEventListener('DOMContentLoaded', function() {
  new DataTable('#filament-summary-table', {
    ordering: true,
    searching: false,
    paging: false,
    info: false,
    drawCallback: function() { applyPeriodDisplay(); },
  });

  // Card click: filter by material
  document.querySelectorAll('.filament-card').forEach(function(card) {
    card.addEventListener('click', function() {
      filterByMaterial(card.dataset.material);
    });
  });

  // Swatch click: filter by material + family
  document.querySelectorAll('.swatch').forEach(function(swatch) {
    swatch.addEventListener('click', function(e) {
      e.stopPropagation();
      var card = swatch.closest('.filament-card');
      filterByFamily(card.dataset.material, swatch.dataset.family);
    });
  });

  applyFilters();

  var tableRows = document.querySelectorAll('#filament-summary-table tbody tr');
  var materials = new Set(), subtypes = new Set(), families = new Set();
  tableRows.forEach(function(row) {
    if (row.dataset.material) materials.add(row.dataset.material);
    if (row.dataset.subtype) subtypes.add(row.dataset.subtype);
    if (row.dataset.family) families.add(row.dataset.family);
  });
  function populateSelect(id, values) {
    var sel = document.getElementById(id);
    Array.from(values).sort().forEach(function(v) {
      var opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      sel.appendChild(opt);
    });
  }
  populateSelect('filter-material', materials);
  populateSelect('filter-subtype', subtypes);
  populateSelect('filter-family', families);

  document.getElementById('filter-material').addEventListener('change', function() {
    activeMaterial = this.value || null;
    activeFamily = null;
    document.getElementById('filter-family').value = '';
    applyFilters();
  });
  document.getElementById('filter-subtype').addEventListener('change', function() {
    activeSubtype = this.value || null;
    applyFilters();
  });
  document.getElementById('filter-family').addEventListener('change', function() {
    activeFamily = this.value || null;
    applyFilters();
  });
});
