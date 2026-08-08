/** Кабинет исполнителя: анкета, прайс, отправка на верификацию (уровень 2). */
import { Stack, router } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import {
  ActivityIndicator,
  Banner,
  Button,
  Card,
  Chip,
  Divider,
  HelperText,
  List,
  Snackbar,
  Text,
  TextInput,
} from 'react-native-paper';

import * as DocumentPicker from 'expo-document-picker';

import {
  api,
  ApiError,
  uploadDocument,
  type Category,
  type DocumentType,
  type MyProviderProfile,
  type Service,
  type VerificationDocument,
  type VerificationRequest,
} from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';

/** Документы уровня 2 (п. 4.1 ТЗ) + документы об образовании для уровня 3. */
const DOCUMENT_TYPES: DocumentType[] = [
  'id_card',
  'criminal_record',
  'psych_dispensary',
  'narco_dispensary',
  'education',
];

export default function CabinetScreen() {
  const { t, locale } = useI18n();
  const [profile, setProfile] = useState<MyProviderProfile | null>(null);
  const [verification, setVerification] = useState<VerificationRequest | null>(null);
  const [documents, setDocuments] = useState<VerificationDocument[]>([]);
  const [uploading, setUploading] = useState<DocumentType | null>(null);
  const [services, setServices] = useState<Service[]>([]);
  const [headline, setHeadline] = useState('');
  const [about, setAbout] = useState('');
  const [experience, setExperience] = useState('0');
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snackbar, setSnackbar] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [me, request, categories, docs] = await Promise.all([
      api<MyProviderProfile>('/providers/me'),
      api<VerificationRequest | null>('/providers/me/verification'),
      api<Category[]>(`/catalog/categories?locale=${locale}`, { auth: false }),
      api<VerificationDocument[]>('/me/documents'),
    ]);
    setProfile(me);
    setVerification(request);
    setDocuments(docs);
    setServices(categories.flatMap((category) => category.services));
    setHeadline(me.headline ?? '');
    setAbout(me.about ?? '');
    setExperience(String(me.experience_years));
    setPrices(
      Object.fromEntries(me.services.map((offer) => [offer.service_id, offer.price])),
    );
  }, [locale]);

  useEffect(() => {
    load().catch(() => setError(t('error')));
  }, [load, t]);

  const saveProfile = async () => {
    setSaving(true);
    setError(null);
    try {
      await api('/providers/me', {
        method: 'PATCH',
        body: {
          headline: headline || null,
          about: about || null,
          experience_years: Number(experience) || 0,
        },
      });
      const items = Object.entries(prices)
        .filter(([, price]) => Number(price) > 0)
        .map(([serviceId, price]) => ({
          service_id: serviceId,
          price,
          price_unit: 'hour',
        }));
      await api('/providers/me/services', { method: 'PUT', body: items });
      setSnackbar('✓');
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setSaving(false);
    }
  };

  // Справки eGov принимаются только в PDF (п. 4.2 ТЗ).
  const PDF_ONLY: DocumentType[] = ['criminal_record', 'psych_dispensary', 'narco_dispensary'];

  const pickAndUpload = async (documentType: DocumentType) => {
    setError(null);
    // Согласие на обработку ПДн (текст — от юриста) обязательно до загрузки.
    await api('/me/consents', {
      method: 'POST',
      body: { consent_type: 'background_check', document_version: '1.0' },
    }).catch(() => undefined);
    const result = await DocumentPicker.getDocumentAsync({
      type: PDF_ONLY.includes(documentType) ? ['application/pdf'] : ['image/*', 'application/pdf'],
      copyToCacheDirectory: true,
    });
    if (result.canceled || result.assets.length === 0) return;
    const asset = result.assets[0];
    setUploading(documentType);
    try {
      await uploadDocument(documentType, {
        uri: asset.uri,
        name: asset.name,
        mimeType: asset.mimeType ?? 'application/octet-stream',
      });
      setDocuments(await api<VerificationDocument[]>('/me/documents'));
      setSnackbar('✓');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setUploading(null);
    }
  };

  const submitVerification = async () => {
    setError(null);
    try {
      await api('/providers/me/verification', {
        method: 'POST',
        body: { target_level: 'level_2' },
      });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    }
  };

  if (!profile) {
    return (
      <>
        <Stack.Screen options={{ headerShown: true, title: t('providerCabinet') }} />
        {error ? <Text style={styles.center}>{error}</Text> : <ActivityIndicator style={styles.center} />}
      </>
    );
  }

  const statusKey = `pstatus_${profile.status}` as TranslationKey;
  const canSubmit =
    !verification || ['rejected', 'needs_fix', 'approved'].includes(verification.status);

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: t('providerCabinet') }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Banner visible icon="account-badge">
          {t(statusKey)}
          {verification && verification.status !== 'approved'
            ? ` · ${t(`vstatus_${verification.status}` as TranslationKey)}`
            : ''}
        </Banner>

        <View style={styles.actionsRow}>
          <Button
            mode="outlined"
            icon="clipboard-text-search"
            style={styles.actionButton}
            onPress={() => router.push('/cabinet/feed')}
          >
            {t('requestsFeed')}
          </Button>
          <Button
            mode="outlined"
            icon="calendar-clock"
            style={styles.actionButton}
            onPress={() => router.push('/cabinet/schedule')}
          >
            {t('schedule')}
          </Button>
        </View>

        <TextInput
          label={t('headline')}
          value={headline}
          onChangeText={setHeadline}
          mode="outlined"
          style={styles.field}
        />
        <TextInput
          label={t('aboutMe')}
          value={about}
          onChangeText={setAbout}
          multiline
          numberOfLines={4}
          mode="outlined"
          style={styles.field}
        />
        <TextInput
          label={t('expYears')}
          value={experience}
          onChangeText={setExperience}
          keyboardType="number-pad"
          mode="outlined"
          style={styles.field}
        />

        <Card style={styles.field}>
          <Card.Title title={t('services')} />
          <Card.Content>
            {services.map((service, index) => (
              <React.Fragment key={service.id}>
                {index > 0 ? <Divider style={styles.divider} /> : null}
                <List.Item title={service.name} />
                <View style={styles.priceRow}>
                  <TextInput
                    value={prices[service.id] ?? ''}
                    onChangeText={(value) =>
                      setPrices((current) => ({ ...current, [service.id]: value }))
                    }
                    keyboardType="number-pad"
                    mode="outlined"
                    dense
                    style={styles.priceInput}
                    placeholder="0"
                  />
                  <Chip compact>{t('perHour')}</Chip>
                </View>
              </React.Fragment>
            ))}
          </Card.Content>
        </Card>

        <Card style={styles.field}>
          <Card.Title title={t('documents')} />
          <Card.Content>
            <Button
              mode="text"
              icon="help-circle-outline"
              onPress={() => router.push('/cabinet/egov')}
              style={styles.egovLink}
            >
              {t('egovTitle')}
            </Button>
            {DOCUMENT_TYPES.map((docType, index) => {
              const doc = documents.find((d) => d.document_type === docType);
              const statusLine = doc
                ? t(`dstatus_${doc.status}` as TranslationKey) +
                  (doc.valid_until ? ` · ${t('validUntil')} ${doc.valid_until}` : '') +
                  (doc.rejection_reason ? ` · ${doc.rejection_reason}` : '')
                : undefined;
              return (
                <React.Fragment key={docType}>
                  {index > 0 ? <Divider style={styles.divider} /> : null}
                  <List.Item
                    title={t(`doc_${docType}` as TranslationKey)}
                    description={statusLine}
                    left={(props) => (
                      <List.Icon
                        {...props}
                        icon={
                          doc?.status === 'approved'
                            ? 'check-decagram'
                            : doc?.status === 'rejected' || doc?.status === 'expired'
                              ? 'alert-circle-outline'
                              : doc
                                ? 'clock-outline'
                                : 'file-upload-outline'
                        }
                      />
                    )}
                    right={() => (
                      <Button
                        compact
                        mode="text"
                        loading={uploading === docType}
                        onPress={() => pickAndUpload(docType)}
                      >
                        {t('uploadDocument')}
                      </Button>
                    )}
                  />
                </React.Fragment>
              );
            })}
          </Card.Content>
        </Card>

        {error ? <HelperText type="error">{error}</HelperText> : null}

        <Button mode="contained" onPress={saveProfile} loading={saving} style={styles.field}>
          {t('save')}
        </Button>
        {canSubmit ? (
          <Button
            mode="contained-tonal"
            icon="shield-check"
            onPress={submitVerification}
            style={styles.field}
          >
            {t('submitVerification')}
          </Button>
        ) : null}
        <View style={styles.bottomSpace} />
      </ScrollView>
      <Snackbar visible={snackbar !== null} onDismiss={() => setSnackbar(null)} duration={1500}>
        {snackbar ?? ''}
      </Snackbar>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16 },
  center: { marginTop: 64, textAlign: 'center' },
  actionsRow: { flexDirection: 'row', gap: 8, marginTop: 12 },
  actionButton: { flex: 1 },
  egovLink: { alignSelf: 'flex-start', marginBottom: 4 },
  field: { marginTop: 12 },
  divider: { marginVertical: 4 },
  priceRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  priceInput: { width: 120 },
  bottomSpace: { height: 48 },
});
