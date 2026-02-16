import { ref, nextTick } from 'vue'
import { chatWithContent } from '@/api/content'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

/**
 * AI 对话状态管理 composable
 *
 * @param {Object} options
 * @param {Function} options.getContentId - 获取当前选中内容 ID 的函数
 * @returns {Object}
 */
export function useFeedChat({ getContentId }) {
  const chatMessages = ref([])
  const chatInput = ref('')
  const chatStreaming = ref(false)
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

  function clearChat() {
    cancelChat()
    chatMessages.value = []
    chatInput.value = ''
  }

  function scrollToLastMessage() {
    nextTick(() => {
      if (chatMessagesEndRef.value) {
        chatMessagesEndRef.value.scrollIntoView({ behavior: 'smooth', block: 'end' })
      }
    })
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
    chatAbort,
    chatInputRef,
    chatMessagesEndRef,
    cancelChat,
    clearChat,
    sendChat,
    handleChatKeydown,
    renderChatMarkdown,
  }
}
