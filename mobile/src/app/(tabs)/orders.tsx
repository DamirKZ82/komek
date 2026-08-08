/** Мои заказы: переключение роли, статусы и действия по жизненному циклу (п. 5.3 ТЗ). */
import { useFocusEffect } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import {
  ActivityIndicator,
  Button,
  Card,
  Chip,
  SegmentedButtons,
  Snackbar,
  Text,
} from 'react-native-paper';

import { api, ApiError, type Order, type Page, type Placement } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n, type TranslationKey } from '@/lib/i18n';

/** Доступные действия по статусу заказа и роли смотрящего. */
function orderActions(
  order: Order,
  role: 'customer' | 'provider',
): { key: TranslationKey; path: string; danger?: boolean }[] {
  const actions: { key: TranslationKey; path: string; danger?: boolean }[] = [];
  if (role === 'provider') {
    if (order.status === 'sent') actions.push({ key: 'actionAccept', path: 'accept' });
    if (order.status === 'confirmed') actions.push({ key: 'actionCheckIn', path: 'check-in' });
    if (order.status === 'in_progress')
      actions.push({ key: 'actionCheckOut', path: 'check-out' });
  } else {
    if (order.status === 'accepted') actions.push({ key: 'actionConfirm', path: 'confirm' });
    if (order.status === 'completed') actions.push({ key: 'actionPay', path: 'pay' });
  }
  if (['sent', 'published', 'accepted', 'confirmed'].includes(order.status)) {
    actions.push({ key: 'actionCancel', path: 'cancel', danger: true });
  }
  return actions;
}

const STATUS_COLORS: Record<string, string> = {
  in_progress: '#00796B',
  confirmed: '#0288D1',
  completed: '#7B1FA2',
  paid: '#2E7D32',
  cancelled: '#C62828',
};

export default function OrdersScreen() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [role, setRole] = useState<'customer' | 'provider'>('customer');
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [snackbar, setSnackbar] = useState<string | null>(null);
  const [placements, setPlacements] = useState<Placement[]>([]);

  const load = useCallback(async () => {
    const page = await api<Page<Order>>(`/orders/my?role=${role}`);
    setOrders(page.items);
    if (role === 'customer') {
      setPlacements(await api<Placement[]>('/placements/my'));
    }
  }, [role]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      (async () => {
        setLoading(true);
        try {
          if (active) await load();
        } catch {
          // список остаётся прежним
        } finally {
          if (active) setLoading(false);
        }
      })();
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  const runAction = async (order: Order, path: string) => {
    setBusy(`${order.id}:${path}`);
    try {
      const body =
        path === 'cancel'
          ? { reason: 'Отменено через приложение' }
          : path === 'check-in' || path === 'check-out'
            ? {}
            : undefined;
      await api(`/orders/${order.id}/${path}`, { method: 'POST', body });
      await load();
    } catch (e) {
      setSnackbar(e instanceof ApiError ? e.message : t('error'));
    } finally {
      setBusy(null);
    }
  };

  const renderOrder = ({ item }: { item: Order }) => {
    const start = new Date(item.scheduled_start);
    const statusKey = `status_${item.status}` as TranslationKey;
    const actions = orderActions(item, role);
    return (
      <Card style={styles.card}>
        <Card.Title
          title={`${start.toLocaleDateString('ru-RU')} ${start.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`}
          subtitle={item.comment ?? item.code}
        />
        <Card.Content>
          <View style={styles.row}>
            <Chip compact textStyle={{ color: STATUS_COLORS[item.status] }}>
              {t(statusKey)}
            </Chip>
            <Text variant="titleMedium">
              {Number(item.final_total ?? item.estimated_total).toLocaleString('ru-RU')} ₸
            </Text>
          </View>
        </Card.Content>
        {actions.length > 0 ? (
          <Card.Actions>
            {actions.map((action) => (
              <Button
                key={action.path}
                mode={action.danger ? 'text' : 'contained'}
                textColor={action.danger ? '#C62828' : undefined}
                loading={busy === `${item.id}:${action.path}`}
                disabled={busy !== null}
                onPress={() => runAction(item, action.path)}
              >
                {t(action.key)}
              </Button>
            ))}
          </Card.Actions>
        ) : null}
      </Card>
    );
  };

  return (
    <View style={styles.container}>
      {user?.is_provider ? (
        <SegmentedButtons
          value={role}
          onValueChange={(value) => setRole(value as 'customer' | 'provider')}
          buttons={[
            { value: 'customer', label: t('asCustomer') },
            { value: 'provider', label: t('asProvider') },
          ]}
          style={styles.segments}
        />
      ) : null}
      <FlatList
        data={orders}
        keyExtractor={(item) => item.id}
        renderItem={renderOrder}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        ListHeaderComponent={
          role === 'customer' && placements.some((p) => p.fee_status !== 'waived') ? (
            <>
              {placements
                .filter((p) => p.fee_status === 'pending' || p.fee_status === 'paid')
                .map((placement) => {
                  const guaranteeActive =
                    placement.guarantee_until !== null &&
                    new Date(placement.guarantee_until) > new Date() &&
                    placement.replacement_requested_at === null;
                  return (
                    <Card key={placement.id} style={styles.card}>
                      <Card.Title
                        title={t('placementFeeTitle')}
                        subtitle={t('placementFeeHint')}
                      />
                      <Card.Content>
                        <Text variant="titleLarge">
                          {Number(placement.fee_amount).toLocaleString('ru-RU')} ₸
                        </Text>
                      </Card.Content>
                      <Card.Actions>
                        {placement.fee_status === 'pending' ? (
                          <Button
                            mode="contained"
                            loading={busy === `pl:${placement.id}`}
                            disabled={busy !== null}
                            onPress={async () => {
                              setBusy(`pl:${placement.id}`);
                              try {
                                await api(`/placements/${placement.id}/pay`, { method: 'POST' });
                                await load();
                              } catch (e) {
                                setSnackbar(e instanceof ApiError ? e.message : t('error'));
                              } finally {
                                setBusy(null);
                              }
                            }}
                          >
                            {t('payFee')}
                          </Button>
                        ) : guaranteeActive ? (
                          <Button
                            mode="outlined"
                            loading={busy === `pl:${placement.id}`}
                            disabled={busy !== null}
                            onPress={async () => {
                              setBusy(`pl:${placement.id}`);
                              try {
                                await api(`/placements/${placement.id}/replacement`, {
                                  method: 'POST',
                                  body: { reason: 'Исполнитель не подошёл' },
                                });
                                await load();
                              } catch (e) {
                                setSnackbar(e instanceof ApiError ? e.message : t('error'));
                              } finally {
                                setBusy(null);
                              }
                            }}
                          >
                            {t('requestReplacement')}
                          </Button>
                        ) : null}
                      </Card.Actions>
                    </Card>
                  );
                })}
            </>
          ) : null
        }
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator style={styles.empty} />
          ) : (
            <Text style={styles.empty}>{t('emptyOrders')}</Text>
          )
        }
        contentContainerStyle={styles.list}
      />
      <Snackbar visible={snackbar !== null} onDismiss={() => setSnackbar(null)} duration={2500}>
        {snackbar ?? ''}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  segments: { margin: 12 },
  list: { padding: 12 },
  card: { marginBottom: 12 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  empty: { textAlign: 'center', marginTop: 48, opacity: 0.6 },
});
