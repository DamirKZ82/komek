/** Поиск исполнителей: фильтр по вертикали/услуге, карточки выдачи (п. 5.1 ТЗ). */
import { router } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import {
  ActivityIndicator,
  Avatar,
  Card,
  Chip,
  FAB,
  Text,
} from 'react-native-paper';

import { api, type Category, type Page, type ProviderCard, type Service } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export default function SearchScreen() {
  const { t, locale } = useI18n();
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedService, setSelectedService] = useState<Service | null>(null);
  const [urgentOnly, setUrgentOnly] = useState(false);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [providers, setProviders] = useState<ProviderCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCategories = useCallback(async () => {
    const data = await api<Category[]>(`/catalog/categories?locale=${locale}`, { auth: false });
    setCategories(data);
  }, [locale]);

  const loadProviders = useCallback(async () => {
    // Избранное — отдельная выдача: повторный заказ в два клика (п. 5.1 ТЗ).
    if (favoritesOnly) {
      setProviders(await api<ProviderCard[]>('/providers/favorites'));
      return;
    }
    const params = new URLSearchParams();
    if (selectedService) params.set('service_id', selectedService.id);
    if (urgentOnly) params.set('urgent_only', 'true');
    const page = await api<Page<ProviderCard>>(`/providers/search?${params.toString()}`);
    setProviders(page.items);
  }, [selectedService, urgentOnly, favoritesOnly]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await Promise.all([loadCategories(), loadProviders()]);
      } catch {
        setError(t('error'));
      } finally {
        setLoading(false);
      }
    })();
  }, [loadCategories, loadProviders, t]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadProviders();
    } finally {
      setRefreshing(false);
    }
  }, [loadProviders]);

  const services = categories.flatMap((c) => c.services);

  const renderProvider = ({ item }: { item: ProviderCard }) => {
    const name = [item.first_name, item.last_name].filter(Boolean).join(' ') || '—';
    const initials = name
      .split(' ')
      .map((part) => part[0])
      .join('')
      .toUpperCase();
    return (
      <Card
        style={styles.card}
        onPress={() => router.push({ pathname: '/provider/[id]', params: { id: item.user_id } })}
      >
        <Card.Title
          title={name}
          subtitle={item.headline ?? ''}
          left={(props) => <Avatar.Text {...props} label={initials || '?'} />}
        />
        <Card.Content>
          <View style={styles.badges}>
            {item.verification_level === 'level_3' ? (
              <Chip compact icon="shield-star">
                {t('verifiedLevel3')}
              </Chip>
            ) : item.verification_level === 'level_2' ? (
              <Chip compact icon="shield-check">
                {t('verifiedLevel2')}
              </Chip>
            ) : null}
            {item.rating_avg ? (
              <Chip compact icon="star">
                {item.rating_avg} ({item.rating_count})
              </Chip>
            ) : null}
            {item.experience_years > 0 ? (
              <Chip compact>{`${item.experience_years} ${t('experienceYears')}`}</Chip>
            ) : null}
            {item.min_price ? (
              <Chip compact icon="cash">{`${Number(item.min_price).toLocaleString('ru-RU')} ${t('perHour')}`}</Chip>
            ) : null}
          </View>
        </Card.Content>
      </Card>
    );
  };

  return (
    <View style={styles.container}>
      <FlatList
        data={providers}
        keyExtractor={(item) => item.user_id}
        renderItem={renderProvider}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        ListHeaderComponent={
          <View style={styles.filters}>
            <FlatList
              horizontal
              showsHorizontalScrollIndicator={false}
              data={services}
              keyExtractor={(s) => s.id}
              renderItem={({ item: service }) => (
                <Chip
                  selected={selectedService?.id === service.id}
                  onPress={() =>
                    setSelectedService(selectedService?.id === service.id ? null : service)
                  }
                  style={styles.filterChip}
                >
                  {service.name}
                </Chip>
              )}
            />
            <View style={styles.toggleRow}>
              <Chip
                selected={urgentOnly}
                icon="clock-fast"
                onPress={() => setUrgentOnly(!urgentOnly)}
                disabled={favoritesOnly}
              >
                {t('urgentToday')}
              </Chip>
              <Chip
                selected={favoritesOnly}
                icon="heart"
                onPress={() => setFavoritesOnly(!favoritesOnly)}
              >
                {t('favorites')}
              </Chip>
            </View>
          </View>
        }
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator style={styles.empty} />
          ) : (
            <Text style={styles.empty}>
              {error ?? (favoritesOnly ? t('emptyFavorites') : t('noResults'))}
            </Text>
          )
        }
        contentContainerStyle={styles.list}
      />
      <FAB
        icon="plus"
        label={t('newOrder')}
        style={styles.fab}
        onPress={() => router.push('/order/new')}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  list: { padding: 12 },
  filters: { marginBottom: 8, gap: 8 },
  filterChip: { marginRight: 8 },
  toggleRow: { flexDirection: 'row', gap: 8, alignSelf: 'flex-start' },
  card: { marginBottom: 12 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  empty: { textAlign: 'center', marginTop: 48, opacity: 0.6 },
  fab: { position: 'absolute', right: 16, bottom: 16 },
});
