/** Входная точка: гость — на логин, авторизованный — в приложение. */
import { Redirect } from 'expo-router';
import React from 'react';
import { ActivityIndicator, View } from 'react-native';

import { useAuth } from '@/lib/auth';

export default function Index() {
  const { user, initializing } = useAuth();
  if (initializing) {
    return (
      <View style={{ flex: 1, justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }
  return user ? <Redirect href="/(tabs)/search" /> : <Redirect href="/(auth)/login" />;
}
