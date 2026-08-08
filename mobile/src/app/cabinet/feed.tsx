/** Лента открытых заявок для исполнителя + отклик со своей ценой. */
import { Stack } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import {
  ActivityIndicator,
  Button,
  Card,
  Chip,
  Dialog,
  HelperText,
  Portal,
  Snackbar,
  Text,
  TextInput,
} from 'react-native-paper';

import { api, ApiError, type Order, type Page } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export default function FeedScreen() {
  const { t } = useI18n();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<Order | null>(null);
  const [price, setPrice] = useState('');
  const [message, setMessage] = useState('');
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [snackbar, setSnackbar] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api<Page<Order>>('/orders/feed');
      setOrders(page.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('error'));
    }
  }, [t]);

  useEffect(() => {
    (async () => {
      await load();
      setLoading(false);
    })();
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  const openDialog = (order: Order) => {
    setTarget(order);
    setPrice(order.unit_price);
    setMessage('');
    setDialogError(null);
  };

  const respond = async () => {
    if (!target) return;
    setSending(true);
    setDialogError(null);
    try {
      await api(`/orders/${target.id}/responses`, {
        method: 'POST',
        body: {
          offered_price: price || undefined,
          message: message || undefined,
        },
      });
      setTarget(null);
      setSnackbar(t('responded'));
      await load();
    } catch (e) {
      setDialogError(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setSending(false);
    }
  };

  const renderOrder = ({ item }: { item: Order }) => {
    const start = new Date(item.scheduled_start);
    return (
      <Card style={styles.card}>
        <Card.Title
          title={`${start.toLocaleDateString('ru-RU')} ${start.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`}
          subtitle={item.comment ?? item.code}
        />
        <Card.Content>
          <View style={styles.row}>
            {item.is_urgent ? (
              <Chip compact icon="clock-fast">
                {t('urgentToday')}
              </Chip>
            ) : null}
            <Chip compact icon="cash">
              {`${Number(item.unit_price).toLocaleString('ru-RU')} ${t('perHour')}`}
            </Chip>
          </View>
        </Card.Content>
        <Card.Actions>
          <Button mode="contained" onPress={() => openDialog(item)}>
            {t('respond')}
          </Button>
        </Card.Actions>
      </Card>
    );
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: t('requestsFeed') }} />
      <FlatList
        data={orders}
        keyExtractor={(item) => item.id}
        renderItem={renderOrder}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator style={styles.empty} />
          ) : (
            <Text style={styles.empty}>{error ?? t('emptyFeed')}</Text>
          )
        }
        contentContainerStyle={styles.list}
      />
      <Portal>
        <Dialog visible={target !== null} onDismiss={() => setTarget(null)}>
          <Dialog.Title>{t('respond')}</Dialog.Title>
          <Dialog.Content>
            <TextInput
              label={t('yourPrice')}
              value={price}
              onChangeText={setPrice}
              keyboardType="number-pad"
              mode="outlined"
            />
            <TextInput
              label={t('responseMessage')}
              value={message}
              onChangeText={setMessage}
              multiline
              mode="outlined"
              style={styles.dialogField}
            />
            {dialogError ? <HelperText type="error">{dialogError}</HelperText> : null}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={respond} loading={sending} disabled={sending}>
              {t('send')}
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
      <Snackbar visible={snackbar !== null} onDismiss={() => setSnackbar(null)} duration={1500}>
        {snackbar ?? ''}
      </Snackbar>
    </>
  );
}

const styles = StyleSheet.create({
  list: { padding: 12 },
  card: { marginBottom: 12 },
  row: { flexDirection: 'row', gap: 8 },
  empty: { textAlign: 'center', marginTop: 48, opacity: 0.6 },
  dialogField: { marginTop: 12 },
});
