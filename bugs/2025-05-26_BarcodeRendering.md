# Bug Report: Barcode Rendering Failing

## Summary

I have tried running the current software version live on the master branch from three different ways, and each
produces a different result when clicking on the “Print Unique Label” button from /edit/232/. This bug holds for all
inventory items, but I will use ID 232 for an example.

## Code Details

- See [GitHub](https://github.com/jamescoller/inventory_management)

## Environment

| Property         | Value                        |
|------------------|------------------------------|
| Deployment       | Synology NAS                 |
| Container        | Docker                       |
| Access via       | Remote via Safari            |
| Access Base Link | http://knowledge.local:8080/ |

The instance is running deployed on the Synology NAS via Docker, and I access the webpage from
http://knowledge.local:8080/edit/232/ from Safari on a MacBook Pro located on the local network.

Note: I can also reproduce the error via Docker on my local development computer (mac) and by deploying it via my
virtual environment within PyCharm.

### Steps to Reproduce

1. Navigate to http://knowledge.local:8080/edit/232/
2. Click on the button "Print Unique Label"
3. Click on "View Barcode" in the success message.

### Error Details

- On /edit/232/ the success message pops up that the label was printed (so it’s getting to line 73 in views.py).
- When I click on “view barcode” and redirect to /print_barcode/232/unique/, the screen shows the message:
  > Barcode generation failed: 'HttpResponse' object has no attribute ‘save’
- I believe this message comes from views.py line 56.
- I think this is due to a failure at line 49, but I wonder if it only fails when trying to look at the barcode that
  has been printed.
- The barcode does not actually print.
- The webpage console shows no errors on either page.

## Webpage Details

#### /edit/[id]/

```html

<body data-new-gr-c-s-check-loaded="9.78.0" data-gr-ext-installed="">

<nav class="navbar navbar-expand-lg bg-primary" data-bs-theme="dark">
	<div class="container-fluid">
		<a class="navbar-brand" href="/">Inventory Manager</a>
		<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav"
				aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
			<span class="navbar-toggler-icon"></span>
		</button>
		<div class="collapse navbar-collapse justify-content-end" id="navbarNav">
			<ul class="navbar-nav">

				<li class="nav-item">
					<a class="nav-link" href="#">jcoller</a>
				</li>

				<li class="nav-item">
					<a class="nav-link" href="/admin/">Admin</a>
				</li>


				<li class="nav-item">
					<a class="nav-link" href="/logout/">Sign Out</a>
				</li>


			</ul>
		</div>
	</div>
</nav>


<div class="container py-4">
	<h2>Edit Inventory Item</h2>

	<form method="post">
		<input type="hidden" name="csrfmiddlewaretoken"
			   value="086po9YW7WtXdwEkdYs5ioe44qUZy9b560R9wGN388dJBd7Lr8AKpCBo9P6oo7f6">
		<p>
			<label for="id_location">Location:</label>
			<select name="location" id="id_location">
				<option value="">---------</option>

				<option value="1" selected="">Receiving</option>

				<option value="2">RuPaul</option>

				<option value="3">Scooby Doo</option>

				<option value="4">Dry Storage</option>

				<option value="5">Dryers</option>

				<option value="6">H2Laser</option>

				<option value="7">H2Dreamy</option>

			</select>


		</p>


		<p>
			<label for="id_status">Status:</label>
			<select name="status" id="id_status">
				<option value="1" selected="">new</option>

				<option value="2">in use</option>

				<option value="3">drying</option>

				<option value="4">stored</option>

				<option value="5">depleted</option>

			</select>


		</p>


		<p>
			<label for="id_date_depleted">Date depleted:</label>
			<input type="text" name="date_depleted" id="id_date_depleted">


		</p>

		<button type="submit" class="btn btn-outline-primary">Save</button>
		<a href="/search/" class="btn btn-outline-primary">Cancel</a>
	</form>

	<hr>

	<!-- ✅ This is the HTMX response target -->
	<div id="print-result" class="alert alert-success mt-2">Label printed
		<a href="/print_barcode/232/unique/" target="_blank">View barcode</a>
	</div>

	<!-- ✅ HTMX Print Button (outside the main form!) -->
	<form hx-post="/print_barcode/232/unique/" hx-target="#print-result" hx-swap="outerHTML" method="POST" class="">
		<input type="hidden" name="csrfmiddlewaretoken"
			   value="086po9YW7WtXdwEkdYs5ioe44qUZy9b560R9wGN388dJBd7Lr8AKpCBo9P6oo7f6">
		<button type="submit" class="btn btn-secondary mt-3">
			🖨️ Print Unique Label
		</button>
	</form>

	<form hx-post="/print_barcode/232/upc/" hx-target="#print-result" hx-swap="outerHTML" method="POST">
		<input type="hidden" name="csrfmiddlewaretoken"
			   value="086po9YW7WtXdwEkdYs5ioe44qUZy9b560R9wGN388dJBd7Lr8AKpCBo9P6oo7f6">
		<button type="submit" class="btn btn-secondary mt-3">
			🖨️ Print Generic Item Label
		</button>
	</form>

	<!-- ✅ Optional direct GET fallback links (if needed) -->


</div>


<!-- ✅ jQuery first -->
<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>

<!-- ✅ DataTables after jQuery -->
<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/dataTables.bootstrap5.min.css">
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/dataTables.bootstrap5.min.js"></script>

<!-- ✅ Bootstrap bundle -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.0/dist/js/bootstrap.bundle.min.js"></script>

<!-- ✅ HTMX -->
<script src="https://unpkg.com/htmx.org@2.0.4" crossorigin="anonymous"></script>

<!-- ✅ Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>

<style>
	@media print {
		nav,
		.form-label,
		select,
		.btn,
		.dataTables_length,
		.dataTables_filter,
		.dataTables_info,
		.dataTables_paginate,
		.chart-container,
		canvas,
		.no-print {
			display: none !important;
		}

		body {
			background: white;
		}

		.d-print-block {
			display: block !important;
		}
	}
</style>


</body>
```

#### /print_barcode/[id]/unique/

```html

<body data-new-gr-c-s-check-loaded="9.78.0" data-gr-ext-installed="">Barcode generation failed: 'HttpResponse' object
has no attribute 'save'
</body>
```
