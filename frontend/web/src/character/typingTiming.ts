// 타이핑하는 나무늘보의 박자입니다. 3D 모션과 답변 생성 중 화면의 단계 시간이 같은 값을 씁니다.

/** 한 손이 키를 한 번 누르는 간격(초, 모션 시간 기준). 두 손이 번갈아 치므로 이 시간의 절반마다 한 번씩 톡. */
export const TAP_PERIOD = 1.6;
/** 원본 기본 속도의 0.6배 */
export const TYPING_SPEED = 0.6;
/** 타이핑 동작 한 번(두 손이 한 번씩 톡톡)이 화면에서 걸리는 시간(초). 약 2.7초 */
export const TYPING_LOOP_SECONDS = TAP_PERIOD / TYPING_SPEED;
