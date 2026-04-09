package de.myfrya.app.plugins.scanner;

import android.app.Activity;
import android.net.Uri;
import android.util.Base64;
import android.util.Log;

import androidx.activity.result.ActivityResult;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.IntentSenderRequest;
import androidx.activity.result.contract.ActivityResultContracts;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import com.google.mlkit.vision.documentscanner.GmsDocumentScanner;
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions;
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning;
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.List;

@CapacitorPlugin(name = "FryaScanner")
public class FryaScannerPlugin extends Plugin {

    private ActivityResultLauncher<IntentSenderRequest> scannerLauncher;
    private PluginCall savedCall;

    @Override
    public void load() {
        scannerLauncher = getActivity().registerForActivityResult(
            new ActivityResultContracts.StartIntentSenderForResult(),
            result -> handleScanResult(result)
        );
    }

    @PluginMethod
    public void scan(PluginCall call) {
        savedCall = call;

        int pageLimit = call.getInt("pageLimit", 20);
        boolean enableGalleryImport = call.getBoolean("enableGalleryImport", true);

        GmsDocumentScannerOptions options = new GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(enableGalleryImport)
            .setPageLimit(pageLimit)
            .setResultFormats(
                GmsDocumentScannerOptions.RESULT_FORMAT_PDF,
                GmsDocumentScannerOptions.RESULT_FORMAT_JPEG
            )
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
            .build();

        GmsDocumentScanner scanner = GmsDocumentScanning.getClient(options);

        scanner.getStartScanIntent(getActivity())
            .addOnSuccessListener(intentSender -> {
                scannerLauncher.launch(
                    new IntentSenderRequest.Builder(intentSender).build()
                );
            })
            .addOnFailureListener(e -> {
                call.reject("Scanner konnte nicht gestartet werden: " + e.getMessage());
            });
    }

    private void handleScanResult(ActivityResult result) {
        if (savedCall == null) return;

        if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
            GmsDocumentScanningResult scanResult =
                GmsDocumentScanningResult.fromActivityResultIntent(result.getData());

            if (scanResult == null) {
                savedCall.reject("Scan fehlgeschlagen");
                return;
            }

            JSObject ret = new JSObject();

            // PDF als Base64 fuer direkten Upload
            if (scanResult.getPdf() != null) {
                Uri pdfUri = scanResult.getPdf().getUri();
                ret.put("pdfUri", pdfUri.toString());

                try {
                    InputStream is = getContext().getContentResolver().openInputStream(pdfUri);
                    ByteArrayOutputStream baos = new ByteArrayOutputStream();
                    byte[] buffer = new byte[4096];
                    int len;
                    while ((len = is.read(buffer)) != -1) {
                        baos.write(buffer, 0, len);
                    }
                    is.close();
                    String base64Pdf = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP);
                    ret.put("pdfBase64", base64Pdf);
                } catch (Exception e) {
                    Log.e("FryaScanner", "PDF Base64 Fehler", e);
                }
            }

            // Einzelseiten-URIs
            List<GmsDocumentScanningResult.Page> pages = scanResult.getPages();
            ret.put("pageCount", pages != null ? pages.size() : 0);

            if (pages != null) {
                JSArray pageUris = new JSArray();
                for (GmsDocumentScanningResult.Page page : pages) {
                    pageUris.put(page.getImageUri().toString());
                }
                ret.put("pageUris", pageUris);
            }

            savedCall.resolve(ret);
        } else {
            savedCall.reject("Scan abgebrochen");
        }
        savedCall = null;
    }
}
