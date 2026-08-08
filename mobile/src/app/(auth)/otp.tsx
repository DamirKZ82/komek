/** Ввод SMS-кода. В dev-режиме код приходит с бэкенда и подставляется сам. */
import { router, useLocalSearchParams } from 'expo-router';
import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet } from 'react-native';
import { Button, HelperText, Text, TextInput } from 'react-native-paper';

import { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

export default function OtpScreen() {
  const { t, locale } = useI18n();
  const { verifyOtp, requestOtp } = useAuth();
  const params = useLocalSearchParams<{ phone: string; debugCode?: string }>();
  const [code, setCode] = useState(params.debugCode ?? '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setLoading(true);
    setError(null);
    try {
      await verifyOtp(params.phone, code, locale);
      router.replace('/(tabs)/search');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setLoading(false);
    }
  };

  const resend = async () => {
    setError(null);
    try {
      const result = await requestOtp(params.phone);
      if (result.debug_code) setCode(result.debug_code);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Text variant="headlineMedium" style={styles.title}>
        {t('otpTitle')}
      </Text>
      <Text variant="bodyMedium" style={styles.hint}>
        {t('otpHint')} {params.phone}
      </Text>

      <TextInput
        value={code}
        onChangeText={setCode}
        keyboardType="number-pad"
        maxLength={6}
        autoFocus
        mode="outlined"
        style={styles.input}
      />
      {error ? <HelperText type="error">{error}</HelperText> : null}

      <Button
        mode="contained"
        onPress={submit}
        loading={loading}
        disabled={loading || code.length < 4}
        style={styles.button}
      >
        {t('login')}
      </Button>
      <Button mode="text" onPress={resend} style={styles.button}>
        {t('resend')}
      </Button>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', padding: 24 },
  title: { textAlign: 'center', fontWeight: '700' },
  hint: { textAlign: 'center', marginTop: 8, marginBottom: 24, opacity: 0.7 },
  input: { textAlign: 'center', fontSize: 24, letterSpacing: 8 },
  button: { marginTop: 12 },
});
