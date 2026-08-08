/** Профиль: имя, язык, режим исполнителя, выход. */
import { router } from 'expo-router';
import React, { useState } from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import {
  Button,
  Chip,
  Divider,
  List,
  SegmentedButtons,
  Snackbar,
  TextInput,
} from 'react-native-paper';

import { api, type User } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

export default function ProfileScreen() {
  const { t, locale, setLocale } = useI18n();
  const { user, refreshUser, logout } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name ?? '');
  const [saving, setSaving] = useState(false);
  const [snackbar, setSnackbar] = useState<string | null>(null);

  const saveName = async () => {
    setSaving(true);
    try {
      await api<User>('/me', { method: 'PATCH', body: { first_name: firstName } });
      await refreshUser();
      setSnackbar('✓');
    } catch {
      setSnackbar(t('error'));
    } finally {
      setSaving(false);
    }
  };

  const becomeProvider = async () => {
    try {
      await api('/providers/me', { method: 'POST' });
      await refreshUser();
      setSnackbar('✓');
    } catch {
      setSnackbar(t('error'));
    }
  };

  const verifyIdentity = async () => {
    // Здесь должен запускаться SDK KYC-провайдера (Verigram или аналог) и отдавать
    // токен сессии. До подключения договора бэкенд принимает dev-токен.
    try {
      await api<User>('/me/identity', {
        method: 'POST',
        body: { session_token: 'stub:900101300123' },
      });
      await refreshUser();
      setSnackbar('✓');
    } catch {
      setSnackbar(t('error'));
    }
  };

  const doLogout = async () => {
    await logout();
    router.replace('/(auth)/login');
  };

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <List.Item title={user?.phone ?? ''} left={(props) => <List.Icon {...props} icon="phone" />} />
      <Divider />

      <TextInput
        label={t('myName')}
        value={firstName}
        onChangeText={setFirstName}
        mode="outlined"
        style={styles.input}
      />
      <Button mode="contained-tonal" onPress={saveName} loading={saving} style={styles.button}>
        {t('save')}
      </Button>

      <List.Subheader>{t('language')}</List.Subheader>
      <SegmentedButtons
        value={locale}
        onValueChange={(value) => setLocale(value as 'ru' | 'kk')}
        buttons={[
          { value: 'ru', label: 'Русский' },
          { value: 'kk', label: 'Қазақша' },
        ]}
      />

      {user?.identity_verified_at ? (
        <Chip icon="shield-check" style={styles.section}>
          {t('identityVerified')}
        </Chip>
      ) : (
        <Button
          mode="outlined"
          icon="shield-account"
          onPress={verifyIdentity}
          style={styles.section}
        >
          {t('verifyIdentity')}
        </Button>
      )}

      {user?.is_provider ? (
        <Button
          mode="outlined"
          icon="briefcase"
          onPress={() => router.push('/cabinet')}
          style={styles.section}
        >
          {t('providerCabinet')}
        </Button>
      ) : (
        <Button mode="outlined" icon="briefcase-plus" onPress={becomeProvider} style={styles.section}>
          {t('becomeProvider')}
        </Button>
      )}

      <Button mode="text" textColor="#C62828" onPress={doLogout} style={styles.section}>
        {t('logout')}
      </Button>

      <Snackbar visible={snackbar !== null} onDismiss={() => setSnackbar(null)} duration={1500}>
        {snackbar ?? ''}
      </Snackbar>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16 },
  input: { marginTop: 16 },
  button: { marginTop: 8, alignSelf: 'flex-start' },
  section: { marginTop: 24 },
});
