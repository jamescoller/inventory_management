/* Wires camera buttons (any element with data-scan-target) to the Scanner module
   and refocuses the scan input after each HTMX swap. Re-runs after swaps so the
   buttons rendered inside the body partial get wired too. */
(function () {
  "use strict";

  function wire(root) {
    var scope = root || document;
    var buttons = scope.querySelectorAll("[data-scan-target]");
    Array.prototype.forEach.call(buttons, function (btn) {
      if (btn.dataset.scanWired) return;
      btn.dataset.scanWired = "1";
      if (!window.Scanner || !window.Scanner.supported()) {
        btn.disabled = true;
        btn.title =
          "Camera needs HTTPS — type, use a USB wedge, or scan the QR with your phone's camera.";
        return;
      }
      btn.addEventListener("click", function () {
        var form = document.querySelector(btn.dataset.scanTarget);
        if (!form) return;
        window.Scanner.open({
          mode: btn.dataset.scanMode || "feed",
          onCode: function (code) {
            var input = form.querySelector("input[name=code]");
            input.value = code;
            if (window.htmx) {
              window.htmx.trigger(form, "submit");
            } else {
              form.requestSubmit();
            }
          },
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });
  document.body.addEventListener("htmx:afterSwap", function (e) {
    wire(e.target);
  });
  document.body.addEventListener("htmx:afterSettle", function () {
    var input = document.querySelector("#quick-move-body input[name=code]");
    if (input) input.focus();
  });
})();
