/** Инструкция получения справок в eGov mobile (п. 4.2 шаг 1 ТЗ).
 *
 * Платформа юридически не может запросить справки за исполнителя — документы
 * eGov выдаются только самому гражданину. Поэтому здесь пошаговая инструкция
 * с диплинком в eGov и явное согласие на обработку ПДн перед загрузкой.
 */
import { Stack, router } from 'expo-router';
import React, { useState } from 'react';
import { Linking, ScrollView, StyleSheet, View } from 'react-native';
import { Button, Card, Checkbox, Divider, List, Snackbar, Text } from 'react-native-paper';

import { api } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';

/** Диплинк в приложение eGov mobile; при отсутствии — страница услуг на портале. */
const EGOV_DEEPLINK = 'egovmobile://';
const EGOV_FALLBACK = 'https://egov.kz/cms/ru/services';

const CERTIFICATES: { doc: TranslationKey; validity: TranslationKey }[] = [
  { doc: 'doc_criminal_record', validity: 'egovDays90' },
  { doc: 'doc_psych_dispensary', validity: 'egovDays180' },
  { doc: 'doc_narco_dispensary', validity: 'egovDays180' },
];

const STEPS: TranslationKey[] = ['egovStep1', 'egovStep2', 'egovStep3', 'egovStep4'];

export default function EgovScreen() {
  const { t } = useI18n();
  const [consent, setConsent] = useState(false);
  const [snackbar, setSnackbar] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const openEgov = async () => {
    try {
      if (await Linking.canOpenURL(EGOV_DEEPLINK)) {
        await Linking.openURL(EGOV_DEEPLINK);
        return;
      }
    } catch {
      // упадём на веб-версию ниже
    }
    setSnackbar(t('egovNotInstalled'));
    await Linking.openURL(EGOV_FALLBACK);
  };

  const acceptConsent = async () => {
    setBusy(true);
    try {
      await api('/me/consents', {
        method: 'POST',
        body: { consent_type: 'background_check', document_version: '1.0' },
      });
      router.back();
    } catch {
      setSnackbar(t('error'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: t('egovTitle') }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Text variant="bodyMedium" style={styles.intro}>
          {t('egovIntro')}
        </Text>

        <Card style={styles.card}>
          <Card.Content>
            {STEPS.map((step, index) => (
              <View key={step} style={styles.step}>
                <Text variant="titleMedium" style={styles.stepNumber}>
                  {index + 1}
                </Text>
                <Text style={styles.stepText}>{t(step)}</Text>
              </View>
            ))}
          </Card.Content>
          <Card.Actions>
            <Button mode="contained" icon="open-in-new" onPress={openEgov}>
              {t('egovOpen')}
            </Button>
          </Card.Actions>
        </Card>

        <Card style={styles.card}>
          <Card.Title title={t('documents')} />
          <Card.Content>
            {CERTIFICATES.map((item, index) => (
              <React.Fragment key={item.doc}>
                {index > 0 ? <Divider /> : null}
                <List.Item
                  title={t(item.doc)}
                  description={`${t('egovValidity')}: ${t(item.validity)}`}
                  left={(props) => <List.Icon {...props} icon="file-document-outline" />}
                />
              </React.Fragment>
            ))}
          </Card.Content>
        </Card>

        <Card style={styles.card}>
          <Card.Title title={t('consentTitle')} />
          <Card.Content>
            <Text variant="bodySmall">{t('consentText')}</Text>
            <Checkbox.Item
              label={t('consentAccept')}
              status={consent ? 'checked' : 'unchecked'}
              onPress={() => setConsent(!consent)}
              position="leading"
              style={styles.checkbox}
            />
          </Card.Content>
        </Card>

        <Button
          mode="contained"
          disabled={!consent || busy}
          loading={busy}
          onPress={acceptConsent}
          style={styles.submit}
        >
          {t('save')}
        </Button>
      </ScrollView>
      <Snackbar visible={snackbar !== null} onDismiss={() => setSnackbar(null)} duration={2500}>
        {snackbar ?? ''}
      </Snackbar>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48 },
  intro: { opacity: 0.8, marginBottom: 12 },
  card: { marginBottom: 12 },
  step: { flexDirection: 'row', gap: 12, marginBottom: 12, alignItems: 'flex-start' },
  stepNumber: { width: 24, opacity: 0.6 },
  stepText: { flex: 1 },
  checkbox: { paddingHorizontal: 0, marginTop: 8 },
  submit: { marginTop: 8 },
});
