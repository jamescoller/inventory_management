/* Reusable camera barcode scanner built on the vendored @zxing/browser UMD build.
   Used by quick-move and the audit console. getUserMedia requires a secure context
   (HTTPS or localhost), so we feature-detect and degrade gracefully on plain HTTP. */
(function (global) {
  "use strict";
  var Scanner = {};
  var controls = null;

  Scanner.supported = function () {
    return !!(
      global.isSecureContext &&
      navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia &&
      global.ZXingBrowser
    );
  };

  function stripBarcodeUrl(text) {
    try {
      if (text.indexOf("://") !== -1) {
        var path = new URL(text).pathname; // /barcode/INV-563/
        var parts = path.split("/").filter(Boolean);
        if (parts.length >= 2 && parts[0].toLowerCase() === "barcode") {
          return parts[1];
        }
      }
    } catch (e) {
      /* not a URL — fall through */
    }
    return (text || "").trim();
  }

  Scanner.open = function (opts) {
    // opts: { mode: "feed" | "navigate", onCode: function(code) }
    var modalEl = document.getElementById("scanner-modal");
    var video = document.getElementById("scanner-video");
    if (!modalEl || !video || !Scanner.supported()) {
      return;
    }
    var bsModal = global.bootstrap.Modal.getOrCreateInstance(modalEl);
    bsModal.show();
    var reader = new global.ZXingBrowser.BrowserMultiFormatReader();
    reader.decodeFromVideoDevice(undefined, video, function (result, err, ctrl) {
      controls = ctrl;
      if (result) {
        var raw = result.getText();
        if (controls) controls.stop();
        bsModal.hide();
        if (opts.mode === "navigate") {
          global.location.href = raw;
        } else if (typeof opts.onCode === "function") {
          opts.onCode(stripBarcodeUrl(raw));
        }
      }
    });
    modalEl.addEventListener(
      "hidden.bs.modal",
      function () {
        if (controls) controls.stop();
      },
      { once: true }
    );
  };

  global.Scanner = Scanner;
})(window);
