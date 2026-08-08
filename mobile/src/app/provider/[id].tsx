/** Карточка исполнителя: услуги, отзывы, кнопка «Предложить заказ». */
import { Stack, router, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import {
  ActivityIndicator,
  Avatar,
  Button,
  Card,
  Chip,
  Divider,
  IconButton,
  List,
  Text,
} from 'react-native-paper';

import { api, type ProviderDetail } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export default function ProviderScreen() {
  const { t } = useI18n();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [provider, setProvider] = useState<ProviderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setProvider(await api<ProviderDetail>(`/providers/${id}`));
      } catch {
        setError(t('error'));
      }
    })();
  }, [id, t]);

  const toggleFavorite = async () => {
    if (!provider) return;
    const method = provider.is_favorite ? 'DELETE' : 'PUT';
    setProvider({ ...provider, is_favorite: !provider.is_favorite });
    try {
      await api(`/providers/${id}/favorite`, { method });
    } catch {
      setProvider(provider); // откат
    }
  };

  if (error) return <Text style={styles.center}>{error}</Text>;
  if (!provider) return <ActivityIndicator style={styles.center} />;

  const name = [provider.first_name, provider.last_name].filter(Boolean).join(' ') || '—';
  const initials = name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .toUpperCase();

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          title: name,
          headerRight: () => (
            <IconButton
              icon={provider.is_favorite ? 'heart' : 'heart-outline'}
              onPress={toggleFavorite}
            />
          ),
        }}
      />
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.header}>
          <Avatar.Text size={72} label={initials || '?'} />
          <View style={styles.headerText}>
            <Text variant="headlineSmall">{name}</Text>
            {provider.headline ? (
              <Text variant="bodyMedium" style={styles.muted}>
                {provider.headline}
              </Text>
            ) : null}
          </View>
        </View>

        <View style={styles.badges}>
          {provider.verification_level === 'level_3' ? (
            <Chip icon="shield-star">{t('verifiedLevel3')}</Chip>
          ) : provider.verification_level === 'level_2' ? (
            <Chip icon="shield-check">{t('verifiedLevel2')}</Chip>
          ) : null}
          {provider.rating_avg ? (
            <Chip icon="star">{`${provider.rating_avg} (${provider.rating_count})`}</Chip>
          ) : null}
          {provider.experience_years > 0 ? (
            <Chip>{`${provider.experience_years} ${t('experienceYears')}`}</Chip>
          ) : null}
        </View>

        {provider.about ? (
          <Card style={styles.section}>
            <Card.Title title={t('about')} />
            <Card.Content>
              <Text>{provider.about}</Text>
            </Card.Content>
          </Card>
        ) : null}

        <Card style={styles.section}>
          <Card.Title title={t('services')} />
          <Card.Content>
            {provider.services.map((service, index) => (
              <React.Fragment key={service.id}>
                {index > 0 ? <Divider /> : null}
                <List.Item
                  title={service.service_name ?? service.service_id}
                  right={() => (
                    <Text variant="titleMedium">
                      {Number(service.price).toLocaleString('ru-RU')} ₸/{service.price_unit}
                    </Text>
                  )}
                />
              </React.Fragment>
            ))}
          </Card.Content>
        </Card>

        <Button
          mode="contained"
          icon="calendar-plus"
          style={styles.cta}
          onPress={() =>
            router.push({ pathname: '/order/new', params: { providerId: provider.user_id } })
          }
        >
          {t('orderToProvider')}
        </Button>
        <Button
          mode="outlined"
          icon="chat-outline"
          style={styles.writeButton}
          onPress={async () => {
            const thread = await api<{ id: string }>('/chats', {
              method: 'POST',
              body: { peer_user_id: provider.user_id },
            });
            router.push({ pathname: '/chat/[id]', params: { id: thread.id, peerName: name } });
          }}
        >
          {t('write')}
        </Button>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16 },
  center: { flex: 1, textAlign: 'center', marginTop: 64 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  headerText: { flex: 1 },
  muted: { opacity: 0.7 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 16 },
  section: { marginTop: 16 },
  cta: { marginTop: 24 },
  writeButton: { marginTop: 12, marginBottom: 48 },
});
