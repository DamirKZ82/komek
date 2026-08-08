/** График работы исполнителя (п. 5.2 ТЗ): дни недели + интервал времени. */
import { Stack } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import {
  ActivityIndicator,
  Button,
  HelperText,
  List,
  Snackbar,
  Switch,
  Text,
  TextInput,
} from 'react-native-paper';

import { api, ApiError } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';

interface Slot {
  weekday: number;
  time_from: string;
  time_to: string;
}

interface DayState {
  enabled: boolean;
  from: string;
  to: string;
}

const DEFAULT_DAY: DayState = { enabled: false, from: '09:00', to: '18:00' };
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

export default function ScheduleScreen() {
  const { t } = useI18n();
  const [days, setDays] = useState<DayState[]>(Array.from({ length: 7 }, () => DEFAULT_DAY));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snackbar, setSnackbar] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const slots = await api<Slot[]>('/providers/me/schedule');
        setDays((current) =>
          current.map((day, weekday) => {
            const slot = slots.find((s) => s.weekday === weekday);
            return slot
              ? {
                  enabled: true,
                  from: slot.time_from.slice(0, 5),
                  to: slot.time_to.slice(0, 5),
                }
              : day;
          }),
        );
      } catch {
        setError(t('error'));
      } finally {
        setLoading(false);
      }
    })();
  }, [t]);

  const setDay = (index: number, patch: Partial<DayState>) => {
    setDays((current) =>
      current.map((day, i) => (i === index ? { ...day, ...patch } : day)),
    );
  };

  const save = async () => {
    setError(null);
    const slots: Slot[] = [];
    for (const [weekday, day] of days.entries()) {
      if (!day.enabled) continue;
      if (!TIME_RE.test(day.from) || !TIME_RE.test(day.to) || day.to <= day.from) {
        setError(`${t(`day${weekday}` as TranslationKey)}: ${t('error')}`);
        return;
      }
      slots.push({ weekday, time_from: day.from, time_to: day.to });
    }
    setSaving(true);
    try {
      await api('/providers/me/schedule', { method: 'PUT', body: slots });
      setSnackbar('✓');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <>
        <Stack.Screen options={{ headerShown: true, title: t('schedule') }} />
        <ActivityIndicator style={styles.center} />
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: t('schedule') }} />
      <ScrollView contentContainerStyle={styles.container}>
        <Text variant="bodyMedium" style={styles.hint}>
          {t('scheduleHint')}
        </Text>
        {days.map((day, index) => (
          <View key={index} style={styles.dayRow}>
            <List.Item
              title={t(`day${index}` as TranslationKey)}
              right={() => (
                <Switch
                  value={day.enabled}
                  onValueChange={(value) => setDay(index, { enabled: value })}
                />
              )}
              style={styles.dayTitle}
            />
            {day.enabled ? (
              <View style={styles.timeRow}>
                <TextInput
                  label={t('from')}
                  value={day.from}
                  onChangeText={(value) => setDay(index, { from: value })}
                  mode="outlined"
                  dense
                  style={styles.timeInput}
                  placeholder="09:00"
                />
                <TextInput
                  label={t('to')}
                  value={day.to}
                  onChangeText={(value) => setDay(index, { to: value })}
                  mode="outlined"
                  dense
                  style={styles.timeInput}
                  placeholder="18:00"
                />
              </View>
            ) : null}
          </View>
        ))}
        {error ? <HelperText type="error">{error}</HelperText> : null}
        <Button mode="contained" onPress={save} loading={saving} style={styles.save}>
          {t('save')}
        </Button>
      </ScrollView>
      <Snackbar visible={snackbar !== null} onDismiss={() => setSnackbar(null)} duration={1500}>
        {snackbar ?? ''}
      </Snackbar>
    </>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48 },
  center: { marginTop: 64 },
  hint: { opacity: 0.7, marginBottom: 8 },
  dayRow: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#ccc' },
  dayTitle: { paddingVertical: 0 },
  timeRow: { flexDirection: 'row', gap: 12, paddingBottom: 12, paddingHorizontal: 16 },
  timeInput: { width: 120 },
  save: { marginTop: 24 },
});
