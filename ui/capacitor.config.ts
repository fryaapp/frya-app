import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'de.myfrya.app',
  appName: 'FRYA',
  webDir: 'dist',
  // KEIN server.url — Web-Assets werden eingebaut
  android: {
    backgroundColor: '#1A1110',
    allowMixedContent: false,
    webContentsDebuggingEnabled: true, // Alpha — spaeter false
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 2000,
      backgroundColor: '#1A1110',
      showSpinner: false,
      androidScaleType: 'CENTER_CROP',
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#1A1110',
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
