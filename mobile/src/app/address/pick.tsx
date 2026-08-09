/** Выбор адреса на карте 2GIS: подсказки + точка на карте + обратный геокодинг. */
import { Stack, router, useLocalSearchParams } from 'expo-router';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { ActivityIndicator, Button, List, Surface, Text, TextInput } from 'react-native-paper';

import { MapView } from '@/components/MapView';
import { setPickedAddress } from '@/lib/addressDraft';
import { api, type AddressSuggestion } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export default function AddressPickScreen() {
  const { t } = useI18n();
  const params = useLocalSearchParams<{ lat?: string; lon?: string }>();
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [point, setPoint] = useState<{ latitude: number; longitude: number } | null>(
    params.lat && params.lon
      ? { latitude: Number(params.lat), longitude: Number(params.lon) }
      : null,
  );
  const [address, setAddress] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reverseRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Подсказки с задержкой: 2GIS тарифицирует каждый успешный запрос.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: query.trim() });
        if (point) {
          params.set('lat', String(point.latitude));
          params.set('lon', String(point.longitude));
        }
        setSuggestions(await api<AddressSuggestion[]>(`/geo/suggest?${params}`));
      } catch {
        setSuggestions([]);
      }
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, point]);

  const onPick = useCallback((next: { latitude: number; longitude: number }) => {
    setPoint(next);
    setResolving(true);
    if (reverseRef.current) clearTimeout(reverseRef.current);
    reverseRef.current = setTimeout(async () => {
      try {
        const found = await api<AddressSuggestion | null>(
          `/geo/reverse?lat=${next.latitude}&lon=${next.longitude}`,
        );
        setAddress(found?.full_name ?? null);
      } catch {
        setAddress(null);
      } finally {
        setResolving(false);
      }
    }, 500);
  }, []);

  const chooseSuggestion = (item: AddressSuggestion) => {
    setQuery('');
    setSuggestions([]);
    setAddress(item.full_name);
    if (item.latitude !== null && item.longitude !== null) {
      setPoint({ latitude: item.latitude, longitude: item.longitude });
    }
  };

  const confirm = () => {
    if (!point) return;
    setPickedAddress({ ...point, address });
    router.back();
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: t('pickOnMap') }} />
      <View style={styles.container}>
        <TextInput
          mode="outlined"
          placeholder={t('addressSearch')}
          value={query}
          onChangeText={setQuery}
          left={<TextInput.Icon icon="magnify" />}
          style={styles.search}
        />
        {suggestions.length > 0 ? (
          <Surface elevation={2} style={styles.suggestions}>
            {suggestions.slice(0, 6).map((item, index) => (
              <List.Item
                key={item.id ?? `${item.full_name}-${index}`}
                title={item.name}
                description={item.full_name}
                onPress={() => chooseSuggestion(item)}
              />
            ))}
          </Surface>
        ) : null}

        <MapView
          style={styles.map}
          pickMode
          zoom={16}
          center={point ?? undefined}
          onPick={onPick}
        />

        <Surface elevation={3} style={styles.footer}>
          {resolving ? (
            <View style={styles.row}>
              <ActivityIndicator size="small" />
              <Text style={styles.address}>{t('detectingAddress')}</Text>
            </View>
          ) : (
            <Text style={styles.address}>{address ?? t('addressHint')}</Text>
          )}
          <Button mode="contained" disabled={!point} onPress={confirm}>
            {t('confirmAddress')}
          </Button>
        </Surface>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  search: { margin: 12, marginBottom: 0 },
  suggestions: { marginHorizontal: 12, borderRadius: 8, overflow: 'hidden' },
  map: { flex: 1, margin: 12, borderRadius: 12 },
  footer: { padding: 16, gap: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  address: { flex: 1 },
});
