"""
schedule_distributor.py — Ядро алгоритма распределения часов KALIX SaaS.

Реализует:
1. Равномерное распределение годового пула часов (напр. 120ч) по доступным календарным слотам.
2. КРИТИЧЕСКОЕ ПРАВИЛО РАЗРЕШЕНИЯ КОНФЛИКТОВ:
   Если двум группам на одно и то же время требуется один преподаватель или кабинет,
   приоритет отдается группе, у которой осталось БОЛЬШЕ нераспределенных часов (max remaining_hours).
"""
from typing import List, Dict, Any, Set, Tuple, Optional
from datetime import date, time
from collections import defaultdict


class ScheduleDistributor:
    def __init__(
        self,
        calendar_slots: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
        curriculum_items: List[Dict[str, Any]],
        max_daily_subject_hours: int = 3,
        pedagogical_boost: int = 15
    ):
        """
        :param calendar_slots: Хронологический список слотов от generate_academic_calendar_slots
        :param groups: Список групп [{'id': 1, 'name': 'ИТ-21'}, ...]
        :param curriculum_items: Список предметов с часами:
               [{'id': 101, 'group_id': 1, 'subject_name': 'Математика',
                 'teacher_id': 10, 'preferred_room_id': 1,
                 'total_hours': 120, 'remaining_hours': 120}, ...]
        :param max_daily_subject_hours: Максимум часов одного предмета в день для группы (по умолч. 3)
        :param pedagogical_boost: Весовой приоритет для общеобразовательных предметов
        """
        self.calendar_slots = sorted(calendar_slots, key=lambda s: (s['date'], s['slot_number']))
        self.groups = groups
        self.max_daily_subject_hours = max_daily_subject_hours
        self.pedagogical_boost = pedagogical_boost

        # Копируем предметы и инициализируем остатки часов
        self.curriculum = []
        for item in curriculum_items:
            c = dict(item)
            c['total_hours'] = int(c['total_hours'])
            c['remaining_hours'] = int(c.get('remaining_hours', c['total_hours']))
            c['allocated_hours'] = int(c.get('allocated_hours', 0))
            is_gen = c.get('is_general_education')
            if is_gen is None:
                st = c.get('subject_type')
                if st:
                    is_gen = (str(st).lower() in ('general', 'общеобразовательный', 'общеобразовательные'))
                else:
                    s_low = str(c.get('subject_name') or '').lower()
                    voc_keywords = [
                        "производствен", "практик", "программирован", "охрана труда",
                        "правовые основы", "здоровый образ", "бзож", "вычислени",
                        "библиотека яп", "библиотека языков", "мастерск", "лаборатор",
                        "web", "веб", "дизайн", "сетев", "баз данн"
                    ]
                    is_gen = not any(k in s_low for k in voc_keywords)
            c['is_general_education'] = bool(is_gen)
            c['subject_type'] = c.get('subject_type', 'general' if is_gen else 'vocational')
            self.curriculum.append(c)

        # Индексация предметов по группам: group_id -> list of subjects
        self.group_subjects: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for c in self.curriculum:
            self.group_subjects[c['group_id']].append(c)

    def run_distribution(self) -> Dict[str, Any]:
        """
        Основной цикл календарного распределения.
        Возвращает сгенерированное расписание и статистику покрытия часов.
        """
        assignments: List[Dict[str, Any]] = []
        conflicts_resolved: List[Dict[str, Any]] = []

        # Группируем слоты по датам: date -> list of slots
        days_map: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
        for slot in self.calendar_slots:
            days_map[slot['date']].append(slot)

        # Вычисляем целевой темп (pace) для равномерности
        total_days = len(days_map)

        for current_date in sorted(days_map.keys()):
            daily_slots = sorted(days_map[current_date], key=lambda s: s['slot_number'])

            # Трекер нагрузки группы за день: (group_id, subject_id) -> hours
            group_day_subject_hours: Dict[Tuple[int, int], int] = defaultdict(int)

            for slot in daily_slots:
                slot_num = slot['slot_number']
                slot_hours = slot['academic_hours'] # 2 для пары, 1 для урока

                # Ресурсные блокировки на текущий слот
                teacher_occupied: Set[int] = set()
                room_occupied: Set[int] = set()

                # Собираем список кандидатов от каждой группы, у которой еще есть нераспределенные часы
                candidates_per_group: Dict[int, List[Dict[str, Any]]] = {}

                for group in self.groups:
                    gid = group['id']
                    valid_subjects = []

                    for subj in self.group_subjects[gid]:
                        # 1. Проверяем остаток часов
                        if subj['remaining_hours'] < slot_hours:
                            continue

                        # 2. Проверяем лимит часов одного предмета в день и запрет сдваивания пар
                        already_today = group_day_subject_hours[(gid, subj['id'])]

                        # Запрет сдваивания пар: предмет НЕ может получить вторую пару в один день
                        if (slot.get('slot_type') == 'pair' or slot_hours == 2) and already_today >= 2:
                            continue

                        # Общее ограничение дневных часов предмета (по умолчанию максимум 3 часа)
                        if already_today + slot_hours > self.max_daily_subject_hours:
                            continue

                        # Одиночный урок в слоте одиночного урока, пара в слоте пары
                        if (slot.get('slot_type') == 'single_lesson' or slot_hours == 1) and subj['remaining_hours'] % 2 != 0:
                            priority_boost = 500 # Нечетные остатки часов сбрасываем в 1-часовые уроки
                        else:
                            priority_boost = 0

                        # Педагогическая приоритизация: общеобразовательные предметы завершаются раньше
                        ped_boost = self.pedagogical_boost if subj.get('is_general_education', False) else 0

                        valid_subjects.append({
                            'subject': subj,
                            'remaining_hours': subj['remaining_hours'],
                            'score': subj['remaining_hours'] + priority_boost + ped_boost
                        })

                    # Сортируем предметы группы по приоритету (больше remaining_hours = выше приоритет)
                    valid_subjects.sort(key=lambda x: x['score'], reverse=True)
                    candidates_per_group[gid] = valid_subjects

                # =========================================================================
                # РАЗРЕШЕНИЕ КОНФЛИКТОВ И НАЗНАЧЕНИЕ СЛОТОВ
                # Сортируем группы глобально по remaining_hours их лучшего кандидата!
                # =========================================================================
                # Каждая группа предлагает свой лучший доступный предмет.
                # Если ресурс занят, группа с большим remaining_hours получает его первой!
                
                # Создаем заявки групп на текущий слот
                requests = []
                for group in self.groups:
                    gid = group['id']
                    subjs = candidates_per_group.get(gid, [])
                    if subjs:
                        top_candidate = subjs[0]['subject']
                        requests.append({
                            'group_id': gid,
                            'group_name': group['name'],
                            'subject': top_candidate,
                            'remaining_hours': top_candidate['remaining_hours'],
                            'alternatives': [s['subject'] for s in subjs[1:]]
                        })

                # Сортируем все заявки групп по ПРАВИЛУ РАЗРЕШЕНИЯ КОНФЛИКТОВ:
                # ПРИОРИТЕТ ТОЙ ГРУППЕ, У КОТОРОЙ БОЛЬШЕ НЕРАСПРЕДЕЛЕННЫХ ЧАСОВ!
                requests.sort(key=lambda r: r['remaining_hours'], reverse=True)

                for req in requests:
                    gid = req['group_id']
                    chosen_subj = None
                    is_conflict_overridden = False

                    # Пробуем основной предмет
                    subj = req['subject']
                    t_id = subj.get('teacher_id')
                    r_id = subj.get('preferred_room_id')

                    teacher_free = (t_id is None) or (t_id not in teacher_occupied)
                    room_free = (r_id is None) or (r_id not in room_occupied)

                    if teacher_free and room_free:
                        chosen_subj = subj
                    else:
                        # Конфликт! Группа ищет альтернативный предмет из своего пула
                        for alt in req['alternatives']:
                            alt_t = alt.get('teacher_id')
                            alt_r = alt.get('preferred_room_id')
                            if (alt_t is None or alt_t not in teacher_occupied) and \
                               (alt_r is None or alt_r not in room_occupied):
                                chosen_subj = alt
                                conflicts_resolved.append({
                                    'date': str(current_date),
                                    'slot': slot_num,
                                    'group': req['group_name'],
                                    'blocked_by_resource': f"Учитель #{t_id}" if not teacher_free else f"Кабинет #{r_id}",
                                    'switched_to': alt['subject_name']
                                })
                                break

                    # Если нашли подходящий предмет без коллизий для текущей группы
                    if chosen_subj:
                        t_id = chosen_subj.get('teacher_id')
                        r_id = chosen_subj.get('preferred_room_id')

                        if t_id:
                            teacher_occupied.add(t_id)
                        if r_id:
                            room_occupied.add(r_id)

                        # Фиксируем назначение
                        assignments.append({
                            'date': current_date,
                            'day_of_week': slot['day_of_week'],
                            'day_name': slot['day_name'],
                            'slot_number': slot_num,
                            'slot_type': slot['slot_type'],
                            'start_time': slot['start_time'],
                            'end_time': slot['end_time'],
                            'group_id': gid,
                            'group_name': req['group_name'],
                            'subject_id': chosen_subj['id'],
                            'subject_name': chosen_subj['subject_name'],
                            'teacher_id': t_id,
                            'room_id': r_id,
                            'hours': slot_hours
                        })

                        # Обновляем трекеры
                        chosen_subj['remaining_hours'] -= slot_hours
                        chosen_subj['allocated_hours'] += slot_hours
                        group_day_subject_hours[(gid, chosen_subj['id'])] += slot_hours

        # Расчет итоговой статистики покрытия
        total_planned_hours = sum(item['total_hours'] for item in self.curriculum)
        total_allocated_hours = sum(item['allocated_hours'] for item in self.curriculum)
        total_unallocated_hours = sum(item['remaining_hours'] for item in self.curriculum)
        completion_percent = round((total_allocated_hours / total_planned_hours * 100), 1) if total_planned_hours > 0 else 100.0

        return {
            'success': True,
            'total_assignments': len(assignments),
            'total_planned_hours': total_planned_hours,
            'total_allocated_hours': total_allocated_hours,
            'total_unallocated_hours': total_unallocated_hours,
            'completion_percent': completion_percent,
            'conflicts_resolved_count': len(conflicts_resolved),
            'conflicts_log': conflicts_resolved[:20], # Первые 20 для аудита
            'assignments': assignments,
            'updated_curriculum': self.curriculum
        }
