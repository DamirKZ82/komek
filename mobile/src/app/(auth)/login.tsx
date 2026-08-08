/** Экран входа: номер телефона → запрос SMS-кода. */
import { router } from 'expo-router';
import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, View } from 'react-native';
import { Button, HelperText, Text, TextInput } from 'react-native-paper';

import { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

export default function LoginScreen() {
  const { t, locale, setLocale } = useI18n();
  const { requestOtp } = useAuth();
  const [phone, setPhone] = useState('+7');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await requestOtp(phone);
      router.push({
        pathname: '/(auth)/otp',
        params: { phone, debugCode: result.debug_code ?? '' },
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.languageRow}>
        <Button
          mode={locale === 'ru' ? 'contained-tonal' : 'text'}
          compact
          onPress={() => setLocale('ru')}
        >
          Рус
        </Button>
        <Button
          mode={locale === 'kk' ? 'contained-tonal' : 'text'}
          compact
          onPress={() => setLocale('kk')}
        >
          Қаз
        </Button>
      </View>

      <Text variant="displaySmall" style={styles.title}>
        {t('appName')}
      </Text>
      <Text variant="bodyLarge" style={styles.tagline}>
        {t('tagline')}
      </Text>

      <TextInput
        label={t('phoneLabel')}
        placeholder={t('phonePlaceholder')}
        value={phone}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        autoFocus
        mode="outlined"
        style={styles.input}
      />
      {error ? <HelperText type="error">{error}</HelperText> : null}

      <Button
        mode="contained"
        onPress={submit}
        loading={loading}
        disabled={loading || phone.length < 11}
        style={styles.button}
      >
        {t('continue')}
      </Button>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', padding: 24 },
  languageRow: { flexDirection: 'row', justifyContent: 'flex-end', gap: 4 },
  title: { textAlign: 'center', fontWeight: '700' },
  tagline: { textAlign: 'center', marginTop: 8, marginBottom: 32, opacity: 0.7 },
  input: { marginBottom: 4 },
  button: { marginTop: 12 },
});
