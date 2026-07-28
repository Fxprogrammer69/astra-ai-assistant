/**
 * ASTRA Mobile Companion
 * React Native (Expo) — connects to ASTRA desktop via WebSocket
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView,
  StyleSheet, StatusBar, SafeAreaView, Vibration, Platform,
} from 'react-native';

const ASTRA_HOST = process.env.ASTRA_HOST || '192.168.1.100';
const WS_URL = `ws://${ASTRA_HOST}:9001`;

const C = {
  bg:      '#050810',
  surface: '#0a0f1e',
  panel:   '#0d1424',
  border:  '#1a2540',
  accent:  '#00d4ff',
  accent2: '#7b6ef6',
  accent3: '#00ff9d',
  warn:    '#ff6b35',
  text:    '#e8f0fe',
  muted:   '#4a5a7a',
};

// ── WebSocket Hook ────────────────────────────────────────────────────────────
function useASTRASocket(url) {
  const ws = useRef(null);
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [events, setEvents]   = useState([]);

  const connect = useCallback(() => {
    try {
      ws.current = new WebSocket(url);
      ws.current.onopen  = () => setConnected(true);
      ws.current.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
      ws.current.onerror = () => setConnected(false);
      ws.current.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'chat_response') {
            setMessages(prev => [...prev, { role: 'astra', text: data.text, ts: Date.now() }]);
          } else {
            setEvents(prev => [data, ...prev].slice(0, 20));
          }
        } catch (_) {}
      };
    } catch (_) {}
  }, [url]);

  useEffect(() => { connect(); return () => ws.current?.close(); }, [connect]);

  const send = useCallback((payload) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }, []);

  return { connected, messages, setMessages, events, send };
}

// ── Timestamp ─────────────────────────────────────────────────────────────────
const ts = () => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
};

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const { connected, messages, setMessages, events, send } = useASTRASocket(WS_URL);
  const [input, setInput]   = useState('');
  const [tab, setTab]       = useState('chat'); // chat | modes | events
  const scrollRef = useRef(null);

  const sendMsg = () => {
    const text = input.trim();
    if (!text) return;
    setMessages(prev => [...prev, { role: 'user', text, ts: Date.now() }]);
    send({ type: 'chat', text });
    setInput('');
    Vibration.vibrate(30);
  };

  const activateMode = (mode) => {
    send({ type: 'chat', text: `Activate ${mode}` });
    Vibration.vibrate(60);
  };

  const MODES = [
    { name: 'Engineer', color: C.accent,  icon: '</>' },
    { name: 'Student',  color: C.accent2, icon: '📖' },
    { name: 'Founder',  color: C.accent3, icon: '🚀' },
    { name: 'Focus Lock', color: C.warn,  icon: '🔒' },
    { name: 'Trading',  color: '#ffd700', icon: '📈' },
    { name: 'Recovery', color: '#ff9eb5', icon: '💙' },
  ];

  const QUICK = [
    'Summarize my day',
    'Start deep work',
    'Market brief',
    'Plan next 4 hours',
    'Activate focus lock',
  ];

  return (
    <SafeAreaView style={s.safe}>
      <StatusBar barStyle="light-content" backgroundColor={C.bg} />

      {/* Header */}
      <View style={s.header}>
        <Text style={s.logo}>AST<Text style={{ color: C.accent2 }}>RA</Text></Text>
        <View style={[s.pill, { borderColor: connected ? C.accent3 : C.warn }]}>
          <View style={[s.dot, { backgroundColor: connected ? C.accent3 : C.warn }]} />
          <Text style={[s.pillText, { color: connected ? C.accent3 : C.warn }]}>
            {connected ? 'ONLINE' : 'CONNECTING'}
          </Text>
        </View>
      </View>

      {/* Tabs */}
      <View style={s.tabs}>
        {['chat','modes','events'].map(t => (
          <TouchableOpacity key={t} style={[s.tab, tab===t && s.tabActive]} onPress={() => setTab(t)}>
            <Text style={[s.tabText, tab===t && { color: C.accent }]}>{t.toUpperCase()}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Chat Tab */}
      {tab === 'chat' && (
        <View style={s.flex}>
          <ScrollView
            ref={scrollRef}
            style={s.chatLog}
            onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
          >
            {messages.length === 0 && (
              <Text style={s.emptyMsg}>ASTRA is ready. Send a command.</Text>
            )}
            {messages.map((m, i) => (
              <View key={i} style={[s.msgRow, m.role === 'user' && s.msgRowUser]}>
                <Text style={[s.msgWho, m.role === 'user' && { color: C.accent2 }]}>
                  {m.role === 'user' ? 'YOU' : 'ASTRA'} // {ts()}
                </Text>
                <View style={[s.bubble, m.role === 'user' ? s.bubbleUser : s.bubbleAstra]}>
                  <Text style={s.bubbleText}>{m.text}</Text>
                </View>
              </View>
            ))}
          </ScrollView>

          {/* Quick Commands */}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.quickScroll}>
            {QUICK.map((q, i) => (
              <TouchableOpacity key={i} style={s.chip} onPress={() => { setInput(q); }}>
                <Text style={s.chipText}>{q}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Input */}
          <View style={s.inputRow}>
            <TextInput
              style={s.input}
              value={input}
              onChangeText={setInput}
              placeholder="Command ASTRA..."
              placeholderTextColor={C.muted}
              onSubmitEditing={sendMsg}
              returnKeyType="send"
              multiline={false}
            />
            <TouchableOpacity style={s.sendBtn} onPress={sendMsg}>
              <Text style={s.sendIcon}>→</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Modes Tab */}
      {tab === 'modes' && (
        <ScrollView style={s.flex} contentContainerStyle={s.modesGrid}>
          <Text style={s.sectionLabel}>ACTIVATE MODE</Text>
          {MODES.map((m, i) => (
            <TouchableOpacity
              key={i}
              style={[s.modeCard, { borderColor: m.color }]}
              onPress={() => activateMode(m.name)}
              activeOpacity={0.7}
            >
              <Text style={s.modeIcon}>{m.icon}</Text>
              <Text style={[s.modeName, { color: m.color }]}>{m.name}</Text>
              <Text style={s.modeSub}>Tap to activate</Text>
            </TouchableOpacity>
          ))}
          <Text style={s.sectionLabel} style={{ marginTop: 20 }}>QUICK ACTIONS</Text>
          {[
            { label: '⚡ Start Deep Work', cmd: 'Start deep work session' },
            { label: '📊 Daily Summary',   cmd: 'Summarize my day' },
            { label: '🔒 Focus Lock',      cmd: 'Activate focus lock' },
            { label: '📈 Market Brief',    cmd: 'Summarize macro news' },
            { label: '🧠 Memory Summary',  cmd: 'Show memory summary' },
          ].map((a, i) => (
            <TouchableOpacity key={i} style={s.actionRow} onPress={() => {
              send({ type: 'chat', text: a.cmd });
              setTab('chat');
              Vibration.vibrate(30);
            }}>
              <Text style={s.actionLabel}>{a.label}</Text>
              <Text style={{ color: C.muted, fontSize: 14 }}>›</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      {/* Events Tab */}
      {tab === 'events' && (
        <ScrollView style={s.flex}>
          <Text style={[s.sectionLabel, { padding: 12 }]}>LIVE BRAIN EVENTS</Text>
          {events.length === 0 && (
            <Text style={[s.emptyMsg, { padding: 20 }]}>No events yet. Connect to ASTRA desktop.</Text>
          )}
          {events.map((e, i) => (
            <View key={i} style={s.eventRow}>
              <Text style={s.eventType}>{e.type}</Text>
              <Text style={s.eventText}>{e.msg || e.text || JSON.stringify(e).slice(0,80)}</Text>
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const s = StyleSheet.create({
  safe:       { flex:1, backgroundColor: C.bg },
  flex:       { flex:1 },

  header:     { flexDirection:'row', alignItems:'center', justifyContent:'space-between',
                paddingHorizontal:16, paddingVertical:10,
                borderBottomWidth:1, borderBottomColor:C.border,
                backgroundColor:C.surface },
  logo:       { fontFamily: Platform.OS==='ios'?'Courier New':'monospace',
                fontSize:18, fontWeight:'800', color:C.accent, letterSpacing:3 },
  pill:       { flexDirection:'row', alignItems:'center', gap:5,
                paddingHorizontal:10, paddingVertical:4,
                borderRadius:20, borderWidth:1 },
  dot:        { width:6, height:6, borderRadius:3 },
  pillText:   { fontFamily:Platform.OS==='ios'?'Courier New':'monospace', fontSize:9, letterSpacing:1 },

  tabs:       { flexDirection:'row', backgroundColor:C.surface,
                borderBottomWidth:1, borderBottomColor:C.border },
  tab:        { flex:1, paddingVertical:10, alignItems:'center' },
  tabActive:  { borderBottomWidth:2, borderBottomColor:C.accent },
  tabText:    { fontFamily:Platform.OS==='ios'?'Courier New':'monospace',
                fontSize:9, letterSpacing:1.5, color:C.muted },

  chatLog:    { flex:1, padding:12 },
  emptyMsg:   { color:C.muted, fontFamily:Platform.OS==='ios'?'Courier New':'monospace',
                fontSize:11, textAlign:'center', marginTop:40 },
  msgRow:     { marginBottom:10 },
  msgRowUser: { alignItems:'flex-end' },
  msgWho:     { fontFamily:Platform.OS==='ios'?'Courier New':'monospace',
                fontSize:8, color:C.muted, marginBottom:3, letterSpacing:1 },
  bubble:     { maxWidth:'85%', borderRadius:6, padding:10 },
  bubbleAstra:{ backgroundColor:C.panel, borderLeftWidth:2, borderLeftColor:C.accent },
  bubbleUser: { backgroundColor:'rgba(123,110,246,0.1)', borderLeftWidth:2, borderLeftColor:C.accent2 },
  bubbleText: { color:C.text, fontSize:12, lineHeight:18 },

  quickScroll:{ maxHeight:36, paddingLeft:12, paddingBottom:6 },
  chip:       { backgroundColor:C.panel, borderWidth:1, borderColor:C.border,
                borderRadius:20, paddingHorizontal:12, paddingVertical:5,
                marginRight:6, alignSelf:'flex-start' },
  chipText:   { color:C.muted, fontSize:9, fontFamily:Platform.OS==='ios'?'Courier New':'monospace' },

  inputRow:   { flexDirection:'row', alignItems:'center', margin:10,
                backgroundColor:C.panel, borderWidth:1, borderColor:C.border,
                borderRadius:6, paddingHorizontal:12, paddingVertical:6 },
  input:      { flex:1, color:C.text, fontSize:12,
                fontFamily:Platform.OS==='ios'?'Courier New':'monospace' },
  sendBtn:    { backgroundColor:'rgba(0,212,255,0.1)', borderWidth:1,
                borderColor:'rgba(0,212,255,0.3)', width:30, height:30,
                borderRadius:4, alignItems:'center', justifyContent:'center' },
  sendIcon:   { color:C.accent, fontSize:16, fontWeight:'700' },

  modesGrid:  { padding:12, gap:8 },
  sectionLabel:{ fontFamily:Platform.OS==='ios'?'Courier New':'monospace',
                 fontSize:8, letterSpacing:2, color:C.muted, marginBottom:8 },
  modeCard:   { backgroundColor:C.panel, borderWidth:1, borderRadius:6,
                padding:14, flexDirection:'row', alignItems:'center', gap:12 },
  modeIcon:   { fontSize:20, width:28 },
  modeName:   { fontWeight:'700', fontSize:13, flex:1 },
  modeSub:    { color:C.muted, fontSize:10,
                fontFamily:Platform.OS==='ios'?'Courier New':'monospace' },
  actionRow:  { backgroundColor:C.panel, borderWidth:1, borderColor:C.border,
                borderRadius:6, padding:12, flexDirection:'row',
                alignItems:'center', justifyContent:'space-between', marginBottom:6 },
  actionLabel:{ color:C.text, fontSize:12 },

  eventRow:   { borderBottomWidth:1, borderBottomColor:C.border,
                padding:12 },
  eventType:  { fontFamily:Platform.OS==='ios'?'Courier New':'monospace',
                fontSize:8, color:C.accent, letterSpacing:1, marginBottom:3 },
  eventText:  { color:C.muted, fontSize:10, lineHeight:15 },
});
