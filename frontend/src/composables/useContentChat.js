import { ref, nextTick } from 'vue'
import { chatWithContent, getChatHistory, saveChatHistory, deleteChatHistory } from '@/api/content'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

/**
 * 持久化 AI 对话 composable
 *
 * @param {Object} options
 * @param {Function} options.getContentId - 获取当前选中内容 ID 的函数
 * @returns {Object}
 */
export function useContentChat({ getContentId }) {
  const chatMessages = ref([])
  const chatInput = ref('')
  const chatStreaming = ref(false)
  const chatLoading = ref(false)
  const chatAbort = ref(null)
  const chatInputRef = ref(null)
  const chatMessagesEndRef = ref(null)

  function cancelChat() {
    if (chatAbort.value) {
      chatAbort.value.abort()
      chatAbort.value = null
    }
    chatStreaming.value = false
  }

  function scrollToLastMessage() {
    nextTick(() => {
      if (chatMessagesEndRef.value) {
        chatMessagesEndRef.value.scrollIntoView({ behavior: 'smooth', block: 'end' })
      }
    })
  }

  async function loadHistory(contentId) {
    if (!contentId) {
      chatMessages.value = []
      chatInput.value = ''
      return
    }
    cancelChat()
    chatLoading.value = true
    chatInput.value = ''
    try {
      const res = await getChatHistory(contentId)
      if (res.code === 0 && res.data?.messages?.length) {
        chatMessages.value = res.data.messages
        scrollToLastMessage()
      } else {
        chatMessages.value = []
      }
    } catch {
      chatMessages.value = []
    } finally {
      chatLoading.value = false
    }
  }

  async function saveHistory() {
    const contentId = getContentId()
    if (!contentId || chatMessages.value.length === 0) return
    try {
      await saveChatHistory(contentId, chatMessages.value.map(({ role, content }) => ({ role, content })))
    } catch {
      // silent fail — non-critical
    }
  }

  async function clearHistory() {
    const contentId = getContentId()
    cancelChat()
    chatMessages.value = []
    chatInput.value = ''
    if (!contentId) return
    try {
      await deleteChatHistory(contentId)
    } catch {
      // silent fail
    }
  }

  function sendChat() {
    const text = chatInput.value.trim()
    const contentId = getContentId()
    if (!text || chatStreaming.value || !contentId) return

    chatMessages.value.push({ role: 'user', content: text })
    chatInput.value = ''
    chatStreaming.value = true

    // Add placeholder for assistant response
    chatMessages.value.push({ role: 'assistant', content: '' })
    const assistantIdx = chatMessages.value.length - 1
    scrollToLastMessage()

    // Build messages for API (exclude the empty assistant placeholder)
    const apiMessages = chatMessages.value
      .filter((m, i) => i < assistantIdx)
      .map(({ role, content }) => ({ role, content }))

    chatAbort.value = chatWithContent(
      contentId,
      apiMessages,
      (chunk) => {
        chatMessages.value[assistantIdx].content += chunk
        scrollToLastMessage()
      },
      () => {
        chatStreaming.value = false
        chatAbort.value = null
        scrollToLastMessage()
        // Auto-save after assistant response completes
        saveHistory()
      },
      (errMsg) => {
        chatMessages.value[assistantIdx].content = `**错误:** ${errMsg}`
        chatStreaming.value = false
        chatAbort.value = null
        scrollToLastMessage()
      },
    )
  }

  function handleChatKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendChat()
    }
  }

  function renderChatMarkdown(text) {
    return DOMPurify.sanitize(md.render(text))
  }

  return {
    chatMessages,
    chatInput,
    chatStreaming,
    chatLoading,
    chatAbort,
    chatInputRef,
    chatMessagesEndRef,
    cancelChat,
    loadHistory,
    saveHistory,
    clearHistory,
    sendChat,
    handleChatKeydown,
    renderChatMarkdown,
  }
}
