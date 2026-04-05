import { PushNotifications } from '@capacitor/push-notifications';
import { Capacitor } from '@capacitor/core';
import { API_BASE } from '../lib/constants';

export async function initPush(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;

  try {
    const permission = await PushNotifications.requestPermissions();
    if (permission.receive !== 'granted') {
      console.log('[Push] Berechtigung abgelehnt');
      return;
    }

    // Register listeners BEFORE calling register() to avoid race conditions
    PushNotifications.addListener('registrationError', (err) => {
      // FCM-Registrierung fehlgeschlagen (z.B. kein google-services.json oder Emulator)
      console.warn('[Push] Registrierung fehlgeschlagen (kein FCM auf diesem Gerät?):', err.error);
    });

    await PushNotifications.register();

    // FCM-Token ans Backend senden
    PushNotifications.addListener('registration', async (token) => {
      console.log('[Push] FCM Token erhalten:', token.value.slice(0, 20) + '...');
      try {
        const accessToken = localStorage.getItem('access_token');
        await fetch(`${API_BASE}/settings/push-token`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ token: token.value, platform: 'android' }),
        });
      } catch (err) {
        console.error('[Push] Token-Speicherung fehlgeschlagen:', err);
      }
    });

    // Push im Vordergrund empfangen
    PushNotifications.addListener('pushNotificationReceived', (notification) => {
      console.log('[Push] Erhalten im Vordergrund:', notification.title);
      // TODO: In-App-Toast oder Snackbar zeigen
    });

    // Push angetippt (App war im Hintergrund/beendet)
    PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
      console.log('[Push] Angetippt:', action.notification.title);
      const data = action.notification.data as Record<string, string> | undefined;
      if (data?.case_id) {
        // Navigation zur relevanten Seite
        window.location.href = `/case/${data.case_id}`;
      }
    });

    console.log('[Push] Initialisierung erfolgreich');
  } catch (err) {
    console.error('[Push] Initialisierung fehlgeschlagen:', err);
  }
}
