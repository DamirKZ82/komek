/** Регистрация Expo push-токена на бэкенде. Вызывается после входа; web пропускается. */
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api } from './api';

/** SDK 57: getExpoPushTokenAsync требует projectId. При EAS Build он подставляется в конфиг. */
function getProjectId(): string | undefined {
  return (
    Constants.expoConfig?.extra?.eas?.projectId ??
    (Constants as { easConfig?: { projectId?: string } }).easConfig?.projectId
  );
}

export async function registerPushToken(): Promise<void> {
  if (Platform.OS === 'web') return;
  try {
    // Android 13+: канал должен существовать до запроса токена, иначе не появится
    // системный запрос разрешения.
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Komek',
        importance: Notifications.AndroidImportance.HIGH,
      });
    }

    const { status } = await Notifications.requestPermissionsAsync({
      ios: { allowAlert: true, allowBadge: true, allowSound: true },
    });
    if (status !== 'granted') return;

    const projectId = getProjectId();
    if (!projectId) {
      // В Expo Go без настроенного EAS-проекта токен не получить — это не ошибка.
      return;
    }

    const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    await api('/me/devices', {
      method: 'POST',
      body: { platform: Platform.OS, push_token: token },
    });
  } catch {
    // Пуши — best-effort: без разрешения или вне dev-билда просто молчим.
  }
}
