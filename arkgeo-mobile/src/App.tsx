/**
 * ArkGeo Mobile — Main entry point & navigation router.
 */
import React from 'react';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Colors } from './theme';
import { HomeScreen } from './screens/HomeScreen';
import { SafetyTimerScreen } from './screens/SafetyTimerScreen';
import { OfflineQueueScreen } from './screens/OfflineQueueScreen';
import { SettingsScreen } from './screens/SettingsScreen';

const Tab = createBottomTabNavigator();

const ArkGeoTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: Colors.cyan,
    background: Colors.bgDarkest,
    card: Colors.bgDark,
    text: Colors.textPrimary,
    border: Colors.borderDim,
    notification: Colors.emergency,
  },
};

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <NavigationContainer theme={ArkGeoTheme}>
        <Tab.Navigator
          screenOptions={{
            headerStyle: { backgroundColor: Colors.bgDark },
            headerTintColor: Colors.textPrimary,
            tabBarActiveTintColor: Colors.cyan,
            tabBarInactiveTintColor: Colors.textMuted,
            tabBarStyle: { backgroundColor: Colors.bgDark, borderTopColor: Colors.borderDim },
          }}
        >
          <Tab.Screen
            name="Home"
            component={HomeScreen}
            options={{ title: 'HUD', tabBarIcon: ({ color }) => tabIcon('◎', color) }}
          />
          <Tab.Screen
            name="Timer"
            component={SafetyTimerScreen}
            options={{ title: 'Dead-Man', tabBarIcon: ({ color }) => tabIcon('⏱', color) }}
          />
          <Tab.Screen
            name="Queue"
            component={OfflineQueueScreen}
            options={{ title: 'Offline', tabBarIcon: ({ color }) => tabIcon('☁', color) }}
          />
          <Tab.Screen
            name="Settings"
            component={SettingsScreen}
            options={{ title: 'Settings', tabBarIcon: ({ color }) => tabIcon('⚙', color) }}
          />
        </Tab.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

function tabIcon(emoji: string, color: string) {
  // Minimal text-based icon; swap for vector icons in production.
  return null; // react-native-vector-icons would go here
}
