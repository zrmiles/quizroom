import { describe, expect, it } from 'vitest'

import { remainingMs } from '../components/Timer'
import { fishPosition, formatPin, histogram, plural } from './format'
import { blankQuestion, questionProblems, toPayload, withType } from './validate'

describe('questionProblems', () => {
  it('пустой вопрос с одним ответом — три проблемы', () => {
    const p = questionProblems(blankQuestion('single'))
    expect(p).toContain('Добавьте текст вопроса')
    expect(p).toContain('Отметьте верный вариант')
  })

  it('заполненный вопрос с одним ответом проходит', () => {
    const q = blankQuestion('single')
    q.text = 'Самая большая планета?'
    q.options = [
      { text: 'Юпитер', is_correct: true },
      { text: 'Земля', is_correct: false },
    ]
    expect(questionProblems(q)).toEqual([])
  })

  it('«угадай число»: ответ вне шкалы', () => {
    const q = { ...withType(blankQuestion('single'), 'number'), text: 'Год?', number_answer: 300 }
    expect(questionProblems(q)).toEqual(['Ответ вне шкалы'])
  })

  it('«по порядку»: нужно три элемента', () => {
    const q = { ...blankQuestion('order'), text: 'Порядок', options: [{ text: 'a', is_correct: false }] }
    expect(questionProblems(q)).toContain('Нужно хотя бы три элемента')
  })
})

describe('withType', () => {
  it('сохраняет текст и подставляет шкалу по умолчанию', () => {
    const q = withType({ ...blankQuestion('single'), text: 'Вопрос' }, 'number')
    expect(q.text).toBe('Вопрос')
    expect([q.number_min, q.number_max, q.number_answer, q.number_tolerance]).toEqual([0, 100, 50, 10])
    expect(q.options).toEqual([])
  })

  it('для «по порядку» снимает отметки верного', () => {
    const single = { ...blankQuestion('single'), options: [1, 2, 3].map((i) => ({ text: `${i}`, is_correct: i === 1 })) }
    expect(withType(single, 'order').options.every((o) => !o.is_correct)).toBe(true)
  })
})

it('toPayload обрезает пробелы и убирает id', () => {
  const p = toPayload({ ...blankQuestion('single'), id: 5, text: '  Вопрос ', options: [{ id: 1, text: ' a ', is_correct: true }] })
  expect(p.id).toBeUndefined()
  expect(p.text).toBe('Вопрос')
  expect(p.options).toEqual([{ text: 'a', is_correct: true }])
})

describe('format', () => {
  it('PIN делится пробелом', () => expect(formatPin('482913')).toBe('482 913'))
  it('склонения', () => {
    expect(plural(1, 'вопрос', 'вопроса', 'вопросов')).toBe('вопрос')
    expect(plural(3, 'вопрос', 'вопроса', 'вопросов')).toBe('вопроса')
    expect(plural(11, 'вопрос', 'вопроса', 'вопросов')).toBe('вопросов')
    expect(plural(22, 'вопрос', 'вопроса', 'вопросов')).toBe('вопроса')
  })
  it('гистограмма раскладывает по корзинам, края — в крайние', () => {
    const h = histogram([1900, 1961, 1962, 2000], 1900, 2000, 10)
    expect(h.reduce((a, b) => a + b)).toBe(4)
    expect(h[0]).toBe(1)
    expect(h[6]).toBe(2)
    expect(h[9]).toBe(1)
  })
  it('позиция существа стабильна и в пределах аквариума', () => {
    expect(fishPosition(42)).toEqual(fishPosition(42))
    const left = parseFloat(fishPosition(7).left)
    expect(left).toBeGreaterThanOrEqual(4)
    expect(left).toBeLessThanOrEqual(80)
  })
})

describe('таймер', () => {
  it('учитывает смещение часов сервера', () => {
    // Сервер «спешит» на 2 с: до конца остаётся на 2 с меньше.
    expect(remainingMs(10_000, 2_000, 0)).toBe(8_000)
    expect(remainingMs(10_000, 0, 20_000)).toBe(0)
  })
})
