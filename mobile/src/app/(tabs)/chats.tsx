/** Список диалогов. */
import { router, useFocusEffect } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet } from 'react-native';
import { ActivityIndicator, Avatar, Badge, List, Text } from 'react-native-paper';

import { api, type ChatThread } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export default function ChatsScreen() {
  const { t } = useI18n();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setThreads(await api<ChatThread[]>('/chats'));
  }, []);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      (async () => {
        try {
          if (active) await load();
        } catch {
          // остаётся прежний список
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

  const renderThread = ({ item }: { item: ChatThread }) => {
    const name =
      [item.peer.first_name, item.peer.last_name].filter(Boolean).join(' ') || '—';
    const initials = name
      .split(' ')
      .map((part) => part[0])
      .join('')
      .toUpperCase();
    return (
      <List.Item
        title={name}
        description={item.last_message_preview ?? ''}
        left={(props) => <Avatar.Text {...props} size={44} label={initials || '?'} />}
        right={() =>
          item.unread_count > 0 ? <Badge style={styles.badge}>{item.unread_count}</Badge> : null
        }
        onPress={() =>
          router.push({
            pathname: '/chat/[id]',
            params: { id: item.id, peerName: name },
          })
        }
      />
    );
  };

  return (
    <FlatList
      data={threads}
      keyExtractor={(item) => item.id}
      renderItem={renderThread}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator style={styles.empty} />
        ) : (
          <Text style={styles.empty}>{t('emptyChats')}</Text>
        )
      }
    />
  );
}

const styles = StyleSheet.create({
  empty: { textAlign: 'center', marginTop: 48, opacity: 0.6 },
  badge: { alignSelf: 'center' },
});
