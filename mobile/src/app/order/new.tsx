/**
 * Создание заказа. Два сценария (п. 5.1 ТЗ):
 * с providerId — прямой заказ исполнителю, без — публикация заявки на биржу.
 */
import { Stack, router, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import {
  Button,
  Chip,
  HelperText,
  SegmentedButtons,
  Text,
  TextInput,
} from 'react-native-paper';

import { api, ApiError, type Category, type Order, type Service } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

/** Ближайшие дни для выбора без date-picker'а (минимальный MVP-вариант). */
function nextDays(count: number): { label: string; date: Date }[] {
  return Array.from({ length: count }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() + index);
    date.setHours(10, 0, 0, 0);
    return {
      label:
        index === 0
          ? 'Сегодня'
          : index === 1
            ? 'Завтра'
            : date.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric' }),
      date,
    };
  });
}

const HOURS = ['09', '10', '12', '14', '16', '18', '20'];

export default function NewOrderScreen() {
  const { t, locale } = useI18n();
  const { providerId } = useLocalSearchParams<{ providerId?: string }>();
  const [services, setServices] = useState<Service[]>([]);
  const [serviceId, setServiceId] = useState<string | null>(null);
  const [dayIndex, setDayIndex] = useState(0);
  const [hour, setHour] = useState('10');
  const [duration, setDuration] = useState('3');
  const [price, setPrice] = useState('2000');
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const days = useMemo(() => nextDays(7), []);

  useEffect(() => {
    (async () => {
      const categories = await api<Category[]>(`/catalog/categories?locale=${locale}`, {
        auth: false,
      });
      const all = categories.flatMap((category) => category.services);
      setServices(all);
      if (all.length > 0) setServiceId(all[0].id);
    })().catch(() => setError(t('error')));
  }, [locale, t]);

  const submit = async () => {
    if (!serviceId) return;
    setLoading(true);
    setError(null);
    try {
      const start = new Date(days[dayIndex].date);
      start.setHours(Number(hour), 0, 0, 0);
      const end = new Date(start);
      end.setHours(start.getHours() + Number(duration || '2'));

      await api<Order>('/orders', {
        method: 'POST',
        body: {
          service_id: serviceId,
          provider_user_id: providerId || undefined,
          scheduled_start: start.toISOString(),
          scheduled_end: end.toISOString(),
          price_unit: 'hour',
          unit_price: providerId ? undefined : price,
          comment: comment || undefined,
        },
      });
      router.replace('/(tabs)/orders');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: t('newOrder') }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Text variant="titleMedium">{t('services')}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
          {services.map((service) => (
            <Chip
              key={service.id}
              selected={serviceId === service.id}
              onPress={() => setServiceId(service.id)}
              style={styles.chip}
            >
              {service.name}
            </Chip>
          ))}
        </ScrollView>

        <Text variant="titleMedium" style={styles.label}>
          {t('dateStart')}
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
          {days.map((day, index) => (
            <Chip
              key={day.label}
              selected={dayIndex === index}
              onPress={() => setDayIndex(index)}
              style={styles.chip}
            >
              {day.label}
            </Chip>
          ))}
        </ScrollView>
        <SegmentedButtons
          value={hour}
          onValueChange={setHour}
          buttons={HOURS.slice(0, 5).map((h) => ({ value: h, label: `${h}:00` }))}
          style={styles.label}
        />

        <TextInput
          label="Часов"
          value={duration}
          onChangeText={setDuration}
          keyboardType="number-pad"
          mode="outlined"
          style={styles.label}
        />

        {!providerId ? (
          <TextInput
            label={t('pricePerHour')}
            value={price}
            onChangeText={setPrice}
            keyboardType="number-pad"
            mode="outlined"
            style={styles.label}
          />
        ) : null}

        <TextInput
          label={t('orderComment')}
          value={comment}
          onChangeText={setComment}
          multiline
          numberOfLines={3}
          mode="outlined"
          style={styles.label}
        />

        {error ? <HelperText type="error">{error}</HelperText> : null}

        <Button
          mode="contained"
          onPress={submit}
          loading={loading}
          disabled={loading || !serviceId}
          style={styles.submit}
        >
          {providerId ? t('orderToProvider') : t('createOrder')}
        </Button>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16 },
  chipRow: { marginTop: 8 },
  chip: { marginRight: 8 },
  label: { marginTop: 16 },
  submit: { marginTop: 24, marginBottom: 48 },
});
