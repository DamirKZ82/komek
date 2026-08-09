/** Карта 2GIS MapGL (п. 6 ТЗ).
 *
 * Официального React Native SDK у 2GIS нет, поэтому карта рисуется MapGL JS API
 * внутри WebView. На web react-native-webview не работает — там тот же HTML
 * рендерится в iframe.
 *
 * Ключ MapGL приходит с бэкенда (/geo/config): он публичный по своей природе и
 * ограничивается приложением в Platform Manager. Ключ Catalog API в клиент не попадает.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { ActivityIndicator, Text } from 'react-native-paper';
import WebView from 'react-native-webview';

import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export interface MapMarker {
  id: string;
  latitude: number;
  longitude: number;
  label?: string;
}

interface MapConfig {
  map_key: string | null;
  center_latitude: number;
  center_longitude: number;
}

/** Конфиг карты неизменен в рамках сессии — тянем его один раз на всё приложение. */
let configPromise: Promise<MapConfig> | null = null;

function loadMapConfig(): Promise<MapConfig> {
  configPromise ??= api<MapConfig>('/geo/config', { auth: false });
  return configPromise;
}

interface Props {
  markers?: MapMarker[];
  center?: { latitude: number; longitude: number };
  zoom?: number;
  /** Показывать перекрестие в центре и сообщать координаты при перемещении карты. */
  pickMode?: boolean;
  onPick?: (point: { latitude: number; longitude: number }) => void;
  onMarkerPress?: (id: string) => void;
  style?: object;
}

/** HTML карты. Данные подставляются как JSON, чтобы не собирать строки в рантайме. */
function buildHtml(
  key: string,
  center: [number, number],
  zoom: number,
  markers: MapMarker[],
  pickMode: boolean,
): string {
  const payload = JSON.stringify({ key, center, zoom, markers, pickMode });
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <style>
    html, body, #map { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }
    #pin {
      position: absolute; left: 50%; top: 50%; width: 28px; height: 28px;
      margin: -28px 0 0 -14px; pointer-events: none; font-size: 28px; line-height: 28px;
      text-align: center;
    }
  </style>
  <script src="https://mapgl.2gis.com/api/js/v1"></script>
</head>
<body>
  <div id="map"></div>
  <div id="pin" style="display:none">📍</div>
  <script>
    var cfg = ${payload};

    function send(message) {
      var text = JSON.stringify(message);
      if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(text);
      else if (window.parent !== window) window.parent.postMessage(text, '*');
    }

    try {
      var map = new mapgl.Map('map', {
        key: cfg.key,
        center: cfg.center,
        zoom: cfg.zoom,
        zoomControl: false,
      });

      cfg.markers.forEach(function (item) {
        var marker = new mapgl.Marker(map, {
          coordinates: [item.longitude, item.latitude],
          label: item.label ? { text: item.label, offset: [0, -60] } : undefined,
        });
        marker.on('click', function () {
          send({ type: 'marker', id: item.id });
        });
      });

      if (cfg.pickMode) {
        document.getElementById('pin').style.display = 'block';
        // Точка выбирается центром карты: пользователь двигает карту под пин.
        map.on('moveend', function () {
          var c = map.getCenter();
          send({ type: 'pick', longitude: c[0], latitude: c[1] });
        });
        map.on('click', function (event) {
          map.setCenter(event.lngLat);
        });
      }

      map.on('idle', function () {
        send({ type: 'ready' });
      });
    } catch (error) {
      send({ type: 'error', message: String(error) });
    }
  </script>
</body>
</html>`;
}

export function MapView({
  markers = [],
  center,
  zoom = 12,
  pickMode = false,
  onPick,
  onMarkerPress,
  style,
}: Props) {
  const { t } = useI18n();
  const [config, setConfig] = useState<MapConfig | null>(null);
  const [failed, setFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    let active = true;
    loadMapConfig()
      .then((value) => active && setConfig(value))
      .catch(() => {
        configPromise = null; // разрешаем повтор после сбоя сети
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleMessage = useCallback(
    (raw: string) => {
      try {
        const message = JSON.parse(raw);
        if (message.type === 'pick' && onPick) {
          onPick({ latitude: message.latitude, longitude: message.longitude });
        } else if (message.type === 'marker' && onMarkerPress) {
          onMarkerPress(message.id);
        }
      } catch {
        // мусорное сообщение из webview игнорируем
      }
    },
    [onPick, onMarkerPress],
  );

  // На web сообщения приходят через window.postMessage из iframe.
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const listener = (event: MessageEvent) => {
      if (typeof event.data === 'string') handleMessage(event.data);
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [handleMessage]);

  const html = useMemo(() => {
    if (!config?.map_key) return null;
    const point: [number, number] = center
      ? [center.longitude, center.latitude]
      : [config.center_longitude, config.center_latitude];
    return buildHtml(config.map_key, point, zoom, markers, pickMode);
  }, [config, center, zoom, markers, pickMode]);

  if (failed || (config && !config.map_key)) {
    // Ключ не настроен — честно говорим об этом вместо пустого прямоугольника.
    return (
      <View style={[styles.placeholder, style]}>
        <Text style={styles.placeholderText}>{t('mapUnavailable')}</Text>
      </View>
    );
  }

  if (!html) {
    return (
      <View style={[styles.placeholder, style]}>
        <ActivityIndicator />
      </View>
    );
  }

  if (Platform.OS === 'web') {
    return (
      <View style={[styles.container, style]}>
        {React.createElement('iframe', {
          ref: iframeRef,
          srcDoc: html,
          style: { width: '100%', height: '100%', border: 'none' },
        })}
      </View>
    );
  }

  return (
    <View style={[styles.container, style]}>
      <WebView
        originWhitelist={['*']}
        source={{ html }}
        style={styles.webview}
        onMessage={(event) => handleMessage(event.nativeEvent.data)}
        javaScriptEnabled
        domStorageEnabled
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, overflow: 'hidden' },
  webview: { flex: 1, backgroundColor: 'transparent' },
  placeholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#ECEFF1',
  },
  placeholderText: { opacity: 0.6, textAlign: 'center', paddingHorizontal: 24 },
});
