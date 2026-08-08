/** Экран диалога: текст, фото и голосовые. Контакты маскируются до оплаты (п. 5.4 ТЗ). */
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  useAudioPlayer,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import * as ImagePicker from 'expo-image-picker';
import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  FlatList,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  View,
} from 'react-native';
import { Banner, IconButton, Surface, Text, TextInput } from 'react-native-paper';

import {
  api,
  attachmentUrl,
  getAccessToken,
  sendChatAttachment,
  type ChatMessage,
  type ChatThread,
  type Page,
} from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

function VoiceBubble({ url, headers, seconds }: {
  url: string;
  headers: Record<string, string>;
  seconds: number | null;
}) {
  const { t } = useI18n();
  const player = useAudioPlayer({ uri: url, headers });
  return (
    <Pressable onPress={() => (player.playing ? player.pause() : player.play())}>
      <View style={styles.voiceRow}>
        <IconButton icon={player.playing ? 'pause' : 'play'} size={20} />
        <Text>
          {t('voiceMessage')}
          {seconds ? ` · ${seconds} с` : ''}
        </Text>
      </View>
    </Pressable>
  );
}

export default function ChatScreen() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { id, peerName } = useLocalSearchParams<{ id: string; peerName?: string }>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [contactsUnlocked, setContactsUnlocked] = useState(true);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [authHeaders, setAuthHeaders] = useState<Record<string, string>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder);

  const load = useCallback(async () => {
    const page = await api<Page<ChatMessage>>(`/chats/${id}/messages?limit=50`);
    setMessages(page.items);
  }, [id]);

  useEffect(() => {
    load().catch(() => undefined);
    // Дешёвый поллинг раз в 5 секунд; на этапе 2 — WebSocket/пуши.
    pollRef.current = setInterval(() => load().catch(() => undefined), 5000);
    (async () => {
      const token = await getAccessToken();
      if (token) setAuthHeaders({ Authorization: `Bearer ${token}` });
      try {
        const threads = await api<ChatThread[]>('/chats');
        const current = threads.find((thread) => thread.id === id);
        if (current) setContactsUnlocked(current.contacts_unlocked);
      } catch {
        // баннер просто не покажем
      }
    })();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [id, load]);

  const send = async () => {
    const body = draft.trim();
    if (!body) return;
    setSending(true);
    try {
      const message = await api<ChatMessage>(`/chats/${id}/messages`, {
        method: 'POST',
        body: { body },
      });
      setDraft('');
      setMessages((current) => [message, ...current]);
    } finally {
      setSending(false);
    }
  };

  const sendPhoto = async () => {
    // SDK 57: MediaTypeOptions устарел, типы задаются массивом строк.
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.7,
    });
    if (result.canceled || result.assets.length === 0) return;
    const asset = result.assets[0];
    setSending(true);
    try {
      const message = await sendChatAttachment(
        id,
        {
          uri: asset.uri,
          name: asset.fileName ?? 'photo.jpg',
          mimeType: asset.mimeType ?? 'image/jpeg',
        },
        { caption: draft.trim() || undefined },
      );
      setDraft('');
      setMessages((current) => [message, ...current]);
    } finally {
      setSending(false);
    }
  };

  const toggleRecording = async () => {
    if (recorderState.isRecording) {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) return;
      setSending(true);
      try {
        const message = await sendChatAttachment(
          id,
          { uri, name: 'voice.m4a', mimeType: 'audio/m4a' },
          { durationSeconds: (recorderState.durationMillis ?? 0) / 1000 },
        );
        setMessages((current) => [message, ...current]);
      } finally {
        setSending(false);
      }
      return;
    }
    const { granted } = await requestRecordingPermissionsAsync();
    if (!granted) return;
    await recorder.prepareToRecordAsync();
    recorder.record();
  };

  const renderMessage = ({ item }: { item: ChatMessage }) => {
    const isMine = item.sender_id === user?.id;
    const url = attachmentUrl(id, item.id);
    return (
      <Surface
        elevation={1}
        style={[styles.bubble, isMine ? styles.bubbleMine : styles.bubbleTheirs]}
      >
        {item.message_type === 'image' && item.has_attachment ? (
          <Image source={{ uri: url, headers: authHeaders }} style={styles.photo} />
        ) : null}
        {item.message_type === 'audio' && item.has_attachment ? (
          <VoiceBubble url={url} headers={authHeaders} seconds={item.duration_seconds} />
        ) : null}
        {item.body ? <Text>{item.body}</Text> : null}
        <Text variant="labelSmall" style={styles.time}>
          {new Date(item.created_at).toLocaleTimeString('ru-RU', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </Text>
      </Surface>
    );
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: true, title: peerName ?? t('chats') }} />
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={90}
      >
        <Banner visible={!contactsUnlocked} icon="shield-lock">
          {t('contactsMaskedNotice')}
        </Banner>
        <FlatList
          data={messages}
          keyExtractor={(item) => item.id}
          renderItem={renderMessage}
          inverted
          contentContainerStyle={styles.list}
        />
        {recorderState.isRecording ? (
          <Text style={styles.recording}>{t('recording')}</Text>
        ) : null}
        <View style={styles.inputRow}>
          <IconButton icon="image-outline" disabled={sending} onPress={sendPhoto} />
          <IconButton
            icon={recorderState.isRecording ? 'stop-circle' : 'microphone-outline'}
            disabled={sending}
            onPress={toggleRecording}
          />
          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder={t('typeMessage')}
            mode="outlined"
            style={styles.input}
            multiline
          />
          <IconButton
            icon="send"
            mode="contained"
            disabled={sending || draft.trim().length === 0}
            onPress={send}
          />
        </View>
      </KeyboardAvoidingView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  list: { padding: 12 },
  bubble: { padding: 10, borderRadius: 12, marginBottom: 8, maxWidth: '80%' },
  bubbleMine: { alignSelf: 'flex-end', backgroundColor: '#B2DFDB' },
  bubbleTheirs: { alignSelf: 'flex-start' },
  photo: { width: 220, height: 220, borderRadius: 8, marginBottom: 6 },
  voiceRow: { flexDirection: 'row', alignItems: 'center' },
  recording: { textAlign: 'center', paddingVertical: 4, opacity: 0.7 },
  time: { opacity: 0.5, alignSelf: 'flex-end', marginTop: 2 },
  inputRow: { flexDirection: 'row', alignItems: 'flex-end', padding: 8, gap: 0 },
  input: { flex: 1, maxHeight: 120 },
});
