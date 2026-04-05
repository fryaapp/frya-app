import { registerPlugin } from '@capacitor/core';

export interface ScanResult {
  pdfUri: string;
  pdfBase64: string;
  pageCount: number;
  pageUris: string[];
}

export interface FryaScannerPlugin {
  scan(options?: { pageLimit?: number; enableGalleryImport?: boolean }): Promise<ScanResult>;
}

const FryaScanner = registerPlugin<FryaScannerPlugin>('FryaScanner', {
  // Web-Fallback: Plugin wirft einen Fehler, der im UI abgefangen wird
  web: () => Promise.reject(new Error('FryaScanner ist nur in der nativen App verfuegbar')),
});

export default FryaScanner;
