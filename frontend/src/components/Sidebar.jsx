import { useState, useEffect } from 'react';
import {
  ActionIcon,
  Avatar,
  Box,
  Button,
  Divider,
  Group,
  ScrollArea,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { IconLogout, IconMessage, IconPlus, IconTrash } from '@tabler/icons-react';
import { apiFetch } from '../utils/api';

function Sidebar({ activeChatId, onSelectChat, onCreateChat, user, onLogout, onDeleteChat }) {
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (user) {
      fetchChats();
    }
  }, [user, activeChatId]);

  const fetchChats = async () => {
    try {
      const res = await apiFetch('/api/chats', {
        headers: { pragma: 'no-cache', 'cache-control': 'no-cache' },
      });
      if (res.ok) {
        setChats(await res.json());
        setError('');
      } else {
        setError('Could not load your chats.');
      }
    } catch (err) {
      console.error('Failed to load chat history:', err);
    }
  };

  const handleNewChat = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch('/api/chats', { method: 'POST' });
      if (res.ok) {
        const newChat = await res.json();
        setChats((prev) => [newChat, ...prev]);
        onCreateChat(newChat.id);
      } else if (res.status === 401) {
        setError('Your session expired. Please sign in again.');
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || 'Could not create a chat. Please try again.');
      }
    } catch (err) {
      console.error('Failed to create new chat:', err);
      setError('Could not reach the server. Check your connection.');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteChat = async (event, id) => {
    event.stopPropagation();
    if (!window.confirm('Delete this session? This cannot be undone.')) return;
    setError('');
    try {
      const res = await apiFetch(`/api/chats/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setChats((prev) => prev.filter((chat) => chat.id !== id));
        if (onDeleteChat) onDeleteChat(id);
      } else if (res.status === 401) {
        setError('Your session expired. Please sign in again.');
      } else {
        setError('Could not delete that session.');
      }
    } catch (err) {
      console.error('Failed to delete chat:', err);
      setError('Could not reach the server. Check your connection.');
    }
  };

  const truncateTitle = (chat) => {
    if (!chat.messages || chat.messages.length === 0) return 'Empty Chat Session';
    const firstMsg = chat.messages[0].content;
    return firstMsg.length > 28 ? firstMsg.substring(0, 28) + '…' : firstMsg;
  };

  const initials = (user?.display_name || 'GU').substring(0, 2).toUpperCase();

  return (
    <Box
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        width: '100%',
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        overflow: 'hidden',
      }}
    >
      {/* New session */}
      <Box style={{ padding: '16px 12px', borderBottom: '1px solid var(--border-color)' }}>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={handleNewChat}
          loading={loading}
          variant="default"
          fullWidth
        >
          New Session
        </Button>
      </Box>

      {/* Chat list */}
      <ScrollArea style={{ flex: 1 }} offsetScrollbars>
        <Box style={{ padding: '12px 8px' }}>
          <Text
            size="11px"
            fw={700}
            style={{
              letterSpacing: '1.5px',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
              padding: '0 4px 10px',
            }}
          >
            PAST SESSIONS
          </Text>

          {chats.length === 0 ? (
            <Text size="13px" style={{ color: 'var(--text-muted)', padding: '8px 10px' }}>
              No sessions found.
            </Text>
          ) : (
            chats.map((chat) => (
              <UnstyledButton
                key={chat.id}
                className={`ideator-chat-item${chat.id === activeChatId ? ' active' : ''}`}
                onClick={() => onSelectChat(chat.id)}
              >
                <IconMessage size={16} style={{ flexShrink: 0, opacity: 0.7 }} />
                <Text size="14px" truncate style={{ flex: 1, minWidth: 0 }}>
                  {truncateTitle(chat)}
                </Text>
                <Tooltip label="Delete session" withArrow position="top">
                  <ActionIcon
                    className="del"
                    variant="subtle"
                    color="red"
                    size="sm"
                    radius="sm"
                    aria-label="Delete session"
                    onClick={(event) => handleDeleteChat(event, chat.id)}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Tooltip>
              </UnstyledButton>
            ))
          )}

          {error && (
            <Text size="12px" style={{ color: 'var(--text-secondary)', padding: '10px' }}>
              {error}
            </Text>
          )}
        </Box>
      </ScrollArea>

      <Divider />

      {/* Profile */}
      <Box style={{ padding: '12px' }}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap="10px" wrap="nowrap" style={{ minWidth: 0 }}>
            <Avatar color="gray" variant="filled" radius="xl" size={36}>
              {initials}
            </Avatar>
            <Box style={{ minWidth: 0 }}>
              <Text size="sm" fw={600} c="var(--text-primary)" truncate>
                {user?.display_name || 'Guest'}
              </Text>
              <Text size="11px" c="var(--text-muted)">
                Active Session
              </Text>
            </Box>
          </Group>
          <ActionIcon variant="subtle" color="gray" size="lg" aria-label="Sign out" onClick={onLogout}>
            <IconLogout size={18} />
          </ActionIcon>
        </Group>
      </Box>
    </Box>
  );
}

export default Sidebar;
