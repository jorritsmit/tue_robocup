#! /usr/bin/env python
import roslib; 
import rospy
import smach
import subprocess
import inspect
import random
import ed_perception.msg
import actionlib
import actionlib_msgs
import robot_skills.util.msg_constructors as msgs
import geometry_msgs.msg as gm

from collections import namedtuple
# from enum import Enum
from smach_ros import SimpleActionState
from robot_skills.amigo import Amigo
from robot_smach_states.util.designators import DesignatorResolvementError, EdEntityDesignator, AttrDesignator, VariableDesignator, Designator
from ed_perception.msg import FaceLearningGoal, FaceLearningResult
from ed.msg import EntityInfo


# import ipdb; ipdb.set_trace()

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class Pose:
    Standing = 0
    Sitting_down = 1

class Gender:
    Male = 0
    Female = 1

OUT_PREFIX = bcolors.OKBLUE + "[CHALLENGE PERSON RECOGNITION] " + bcolors.ENDC


# ----------------------------------------------------------------------------------------------------


class Location(object):
    def __init__(self, point_stamped, visited, attempts):
        self.point_stamped = point_stamped
        self.visited = visited
        self.attempts = attempts

class FaceAnalysed(object):
    def __init__(self, point_stamped, name, score, pose=Pose.Standing, gender=Gender.Male, inMainCrowd=False):
        self.point_stamped = point_stamped
        self.name = name
        self.score = score
        self.pose = pose
        self.gender = gender
        self.inMainCrowd = inMainCrowd

class PointDesignator(Designator):
    """ Returns a more or less hardcoded designator"""
    def __init__(self, point_stamped=None):
        super(Designator, self).__init__()
        
        self.entity = EntityInfo()

        if not point_stamped == None:
            self.entity.pose.position = point_stamped.point

    def setPoint(self, point_stamped):
        self.entity.pose.position = point_stamped.point
    
    def resolve(self):
        return self.entity


def points_distance(p1, p2):
    print OUT_PREFIX + "Testing ({0},{1},{2}) -> ({3},{4},{5})".format(p1[0], p1[1], p1[2], p2[0], p2[1], p2[2])

    return 2.5



# ----------------------------------------------------------------------------------------------------


class WaitForOperator(smach.State):
    def __init__(self, robot):
        smach.State.__init__(self,outcomes=['success', 'failed'])
        self.robot = robot

    def execute(self):
        print OUT_PREFIX + bcolors.OKBLUE + "WaitForOperator" + bcolors.ENDC

        # Return sucess only when a person is seen in front of the robot, or time-out after a minute

        return 'success'


# ----------------------------------------------------------------------------------------------------

class LookAtPersonInFront(smach.State):
    def __init__(self, robot, lookDown = False):
        smach.State.__init__(self, outcomes=['succeded', 'failed'])
        self.robot = robot
        self.lookDown = lookDown

    def execute(self, robot):
        print OUT_PREFIX + bcolors.OKBLUE + "LookAtPersonInFront" + bcolors.ENDC

        # initialize variables
        foundFace = False
        result = None
        entityData = None
        faces_front = None
        desgnResult = None

        # set robots pose
        self.robot.spindle.high()
        
        # look front, 2 meters high
        # self.robot.head.look_at_standing_person(timeout=4)
        self.robot.head.look_at_point(point_stamped=msgs.PointStamped(3, 0, 2,"amigo/base_link"), end_time=0, timeout=4)
        rospy.sleep(2)  # give time for the percetion algorithms to add the entity

        # create designator
        humanDesignator = EdEntityDesignator(self.robot, type="human")
        dataDesignator = AttrDesignator(humanDesignator, 'data')

        # try to resolve the designator
        try:
            desgnResult = humanDesignator.resolve()
        except DesignatorResolvementError:
            print OUT_PREFIX + "Could not find a human while looking up"
            pass

        # if no person was seen at 2 meters high, look down, because the person might be sitting
        if desgnResult == None and self.lookDown == True:
            # look front, 2 meters high
            self.robot.head.look_at_point(point_stamped=msgs.PointStamped(3, 0, 0,"amigo/base_link"), end_time=0, timeout=4)
            rospy.sleep(2)    # give time for the percetion algorithms to add the entity

            # try to resolve the designator
            try:
                desgnResult = humanDesignator.resolve()
            except DesignatorResolvementError:
                print OUT_PREFIX + "Could not find a human while looking down"
                pass

        # if there is a person in front, try to look at the face
        if desgnResult:
            print OUT_PREFIX + "Found a human!"
    
            # resolve the data designator
            try:
                entityData = dataDesignator.resolve()
            except DesignatorResolvementError:
                print OUT_PREFIX + "Could not resolve dataDesignator"
                pass

            # extract information from data
            if entityData:
                try:
                    # get information on the first face found (cant guarantee its the closest in case there are many)
                    faces_front = entityData["perception_result"]["face_detector"]["faces_front"][0]
                except KeyError, ke:
                    print OUT_PREFIX + "KeyError faces_front: " + ke
                    pass
                except IndexError, ke:
                    print OUT_PREFIX + "IndexError faces_front: " + ke
                    pass

                if faces_front:
                    headGoal = msgs.PointStamped(x=faces_front["map_x"], y=faces_front["map_y"], z=faces_front["map_z"], frame_id="/map")

                    print OUT_PREFIX + "Sending head goal to (" + str(headGoal.point.x) + ", " + str(headGoal.point.y) + ", " + str(headGoal.point.z) + ")"
                    self.robot.head.look_at_point(point_stamped=headGoal, end_time=0, timeout=4)
                    # rospy.sleep(2)

                    foundFace == True            
                else:
                    print OUT_PREFIX + "Could not find anyone in front of the robot. It will just look in front and up."
                    return 'failed'

        if foundFace == True:
            return 'succeded'
        else:
            print OUT_PREFIX + "Could not find anyone in front of the robot. It will just look in front and up."
            return 'failed'


# ----------------------------------------------------------------------------------------------------

class CancelHeadGoals(smach.State):
    def __init__(self, robot):
        smach.State.__init__(self,outcomes=['done'])
        self.robot = robot

    def execute(self, robot):
        print OUT_PREFIX + bcolors.OKBLUE + "CancelHeadGoals" + bcolors.ENDC

        self.robot.head.cancel_goal()

        return 'done'


# ----------------------------------------------------------------------------------------------------


class FindCrowd(smach.State):
    def __init__(self, robot, locations):
        smach.State.__init__(   self, outcomes=['succeded', 'failed'])
        self.robot = robot
        self.locations = locations

    def execute(self, userdata):
        print OUT_PREFIX + bcolors.OKBLUE + "FindCrowd" + bcolors.ENDC


        foundCrowd = False
        foundHuman = False
        crowds = None
        humans = None
        entityData = None
        locationsToVistit = []
        
        # create designators
        crowdDesignator = EdEntityDesignator(self.robot, type="crowd")
        humanDesignator = EdEntityDesignator(self.robot, type="human")        
        
        self.robot.spindle.high()

        # "scan" the room with the head
        # look at 3 meters front, 5 meters right and 2 meters high
        self.robot.head.look_at_point(point_stamped=msgs.PointStamped(3,-5,2,"amigo/base_link"), end_time=0, timeout=4)
        rospy.sleep(2)

        # look at 3 meters front, 5 meters left and 2 meters high
        self.robot.head.look_at_point(point_stamped=msgs.PointStamped(3,5,2,"amigo/base_link"), end_time=0, timeout=4)
        rospy.sleep(2)

        # resolve crowds designator
        try:
            crowds = crowdDesignator.resolve()
        except DesignatorResolvementError:
            foundCrowd = False
            pass

        if crowds:
            # print OUT_PREFIX + "Found a crowd"
            foundCrowd = True
        else:
            print OUT_PREFIX + "Didnt find a crowd"
            foundCrowd = False

        # resolve humans designator
        try:
            humans = humanDesignator.resolve()
        except DesignatorResolvementError:
            pass

        if humans:
            # print OUT_PREFIX + "Found a human"
            foundHuman = True
        else:
            print OUT_PREFIX + "Didn't find humans"
            foundHuman = False

        # if no one was found, return failed, else add locations to list
        if not foundCrowd and not foundHuman:
            print OUT_PREFIX + "Could not find anyone in the room"
            return 'failed'
        else:
        # if a person or crowd was found, add their positions to the list

            print OUT_PREFIX + "Current list of locations: " + str(self.locations.resolve())
            # import ipdb; ipdb.set_trace()

            # resolve crowd locations
            if foundCrowd:
                try:
                    dataDesignator = AttrDesignator(crowdDesignator, 'center_point')
                    entityData = dataDesignator.resolve()
                    print OUT_PREFIX + "Crowd found at:\n" + str(entityData)
                except DesignatorResolvementError:
                    print OUT_PREFIX + "Could not resolve dataDesignator"
                    pass

                if not entityData == None:
                    # add point to locations to visit
                    try:
                        self.locations.current += [Location(point_stamped = msgs.PointStamped(x=entityData.x, y=entityData.y, z=entityData.z, frame_id="/map"),
                                                            visited = False,
                                                            attempts = 0)]
                    except KeyError, ke:
                        print OUT_PREFIX + "KeyError faces_front: " + ke
                        pass
                    except IndexError, ke:
                        print OUT_PREFIX + "IndexError faces_front: " + ke
                        pass
                else:
                    print OUT_PREFIX + bcolors.FAIL + "Unable to get crowd center_point" + bcolors.ENDC

            # resolve human locations
            if foundHuman:
                # resolve the data designator
                try:
                    dataDesignator = AttrDesignator(humanDesignator, 'center_point')
                    entityData = dataDesignator.resolve()
                    print OUT_PREFIX + "Human found at:\n" + str(entityData)
                except DesignatorResolvementError:
                    print OUT_PREFIX + "Could not resolve dataDesignator"
                    pass

                if not entityData == None:
                    # add point to locations to visit
                    try:
                        self.locations.current += [Location(point_stamped = msgs.PointStamped(x=entityData.x, y=entityData.y, z=entityData.z, frame_id="/map"),
                                                            visited = False, 
                                                            attempts = 0)]
                    except KeyError, ke:
                        print OUT_PREFIX + "KeyError faces_front: " + ke
                        pass
                    except IndexError, ke:
                        print OUT_PREFIX + "IndexError faces_front: " + ke
                        pass
                else:
                    print OUT_PREFIX + bcolors.FAIL + "Unable to get human center_point" + bcolors.ENDC
            
            # TODO: Filter the list so there are no dupliacte locations
            print OUT_PREFIX + "Updated locations to visit:" + str(self.locations.resolve())

            return 'succeded'


# ----------------------------------------------------------------------------------------------------


class DescribePeople(smach.State):
    def __init__(self, robot, facesAnalyzedDes):
        smach.State.__init__(   self, 
                                input_keys=['operatorIdx_in'],
                                outcomes=['done'])
        self.robot = robot
        self.facesAnalyzedDes = facesAnalyzedDes

    def execute(self, userdata):
        print OUT_PREFIX + bcolors.OKBLUE + "DescribePeople" + bcolors.ENDC

        numberMale = 0
        numberFemale = 0
        faceList = None

        # try to resolve the crowd designator
        try:
            faceList = self.facesAnalyzedDes.resolve()
        except DesignatorResolvementError:
            print OUT_PREFIX + bcolors.FAIL + "Could not resolve facesAnalyzedDes" + bcolors.ENDC
            pass

        if not faceList == None:
            # Compute crowd details
            # import ipdb; ipdb.set_trace()

            for face in faceList:
                print OUT_PREFIX + "Name: {0}, Score: {1}, Location: ({2},{3},{4}), Pose: {5}, Gender: {6}, Main crowd: {7}".format( \
                    str(face.name), \
                    str(face.score), \
                    str(face.point_stamped.point.x), str(face.point_stamped.point.y), str(face.point_stamped.point.z), \
                    str(face.pose), \
                    str(face.gender), \
                    str(face.inMainCrowd))

                if face.gender == Gender.Male:
                    numberMale += 1
                else:
                    numberFemale += 1

            self.robot.speech.speak("I counted {0} persons in this crowd. {1} males and {2} females.".format( \
                len(faceList), 
                numberMale if numberMale > 0 else "no", 
                numberFemale if numberFemale > 0 else "no"),
                block=False)

            try:
                self.robot.speech.speak("My operator is a {gender}, and {pronoun} is {pose}.".format( \
                    gender = "man" if faceList[userdata.operatorIdx_in].gender == Gender.Male else "woman", \
                    pronoun = "he" if faceList[userdata.operatorIdx_in].gender == Gender.Male else "she", \
                    pose =  "standing up" if faceList[userdata.operatorIdx_in].pose == Pose.Sitting_down else "standing up"), \
                    block=True)
            except KeyError, ke:
                    print OUT_PREFIX + "KeyError userdata.operatorIdx_in:" + str(ke)
                    pass

        else:
            self.robot.speech.speak("I could not find any faces during the challenge.",  block=False)

        return 'done'



# ----------------------------------------------------------------------------------------------------


class PointAtOperator(smach.State):
    def __init__(self, robot):
        smach.State.__init__(self, outcomes=['succeeded', 'failed'])
        self.robot = robot

    def execute(self, robot):
        print OUT_PREFIX + bcolors.OKBLUE + "PointAtOperator" + bcolors.ENDC

        # Get information about the operator and point at the location

        return 'succeeded'


# ----------------------------------------------------------------------------------------------------


# Ask the persons name
class AskPersonName(smach.State):
    def __init__(self, robot, operatorNameDes):
        smach.State.__init__(   self, 
                                outcomes=['succeded', 'failed'],
                                output_keys=['personName_out'])

        self.robot = robot
        self.operatorNameDes = operatorNameDes

    def execute(self, userdata):
        print OUT_PREFIX + bcolors.OKBLUE + "AskPersonName" + bcolors.ENDC

        name = "Mr. Operator"
        userdata.personName_out = name
        self.operatorNameDes.current = name

        self.robot.speech.speak("What is your name?", block=True)
        self.robot.speech.speak("I shall call you " + name + "!", block=False)

        return 'succeded'


# ----------------------------------------------------------------------------------------------------


class GetOperatorLocation(smach.State):
    def __init__(self, robot, facesAnalysedDes, operatorNameDes, operatorLocationDes):
        smach.State.__init__(   self, 
                                output_keys=['operatorIdx_out'],
                                outcomes=['succeeded', 'failed'])

        self.robot = robot
        self.facesAnalysedDes = facesAnalysedDes
        self.operatorLocationDes = operatorLocationDes
        self.operatorNameDes = operatorNameDes

    def execute(self, userdata):
        print OUT_PREFIX + bcolors.OKBLUE + "GetOperatorLocation" + bcolors.ENDC

        lowest_score = 1    # scores are between 0 and 1
        chosen = False
        faceList = None

        # try to resolve the crowd designator
        try:
            faceList = self.facesAnalysedDes.resolve()
        except DesignatorResolvementError:
            print OUT_PREFIX + "Could not resolve faces analysed"
            pass

        if not faceList == None:
            for idx, face in enumerate(faceList):
                # print OUT_PREFIX + "Name: {0}, Score: {1}, Location: ({2},{3},{4})".format( \
                #     str(face.name), \
                #     str(face.score), \
                #     str(face.point_stamped.point.x), str(face.point_stamped.point.y), str(face.point_stamped.point.z))


                # score of 0 is for unidentifies people
                if face.score > 0 and face.score < lowest_score and self.operatorNameDes.resolve() == face.name:
                    lowest_score = face.score
                    operatorIdx = idx
                    self.operatorLocationDes.current.setPoint(point_stamped = msgs.PointStamped(x=face.point_stamped.point.x, y=face.point_stamped.point.y, z=face.point_stamped.point.z, frame_id="/map"))

                    chosen = True

                # TODO: MARK PEOPLE THERE ARE CLOSE TO THE OPERATOR, IN THE "MAIN CROWD" face.inMainCrowd

            if chosen:
                print OUT_PREFIX + "Operator is ({0}): {1} ({2}), Location: ({3},{4},{5})".format(
                    str(operatorIdx),
                    str(faceList[operatorIdx].name),
                    str(faceList[operatorIdx].score),
                    str(faceList[operatorIdx].point_stamped.point.x), str(faceList[operatorIdx].point_stamped.point.y), str(faceList[operatorIdx].point_stamped.point.z))
                
                userdata.operatorIdx_out = operatorIdx
                return 'succeeded'
            else:
                operatorIdx_out = 0
                print OUT_PREFIX + bcolors.FAIL + "Could not choose an operator from the list!" + bcolors.ENDC
                return 'failed'
        else:
            print OUT_PREFIX + bcolors.FAIL + "No faces were analysed!" + bcolors.ENDC
            return 'failed'


# ----------------------------------------------------------------------------------------------------


class AnalyzePerson(smach.State):
    def __init__(self, robot, facesAnalysedDes):
        smach.State.__init__(self, outcomes=['succeded', 'failed'])

        self.robot = robot
        self.facesAnalysedDes = facesAnalysedDes

    def execute(self, userdata):
        print OUT_PREFIX + bcolors.OKBLUE + "AnalyzePerson" + bcolors.ENDC
        
        # initialize variables
        result = None
        entityDataList = []
        recognition_label = None
        recognition_score = None
        humanDesgnResult = None
        crowdDesgnResult = None

        # create designator
        crowdDesignator = EdEntityDesignator(self.robot, criteriafuncs=[lambda entity: entity.type in ["crowd", "human"]])
        crowdDataDesignator = AttrDesignator(crowdDesignator, 'data')

        try:
            crowdDesgnResult = crowdDesignator.resolve()
        except DesignatorResolvementError:
            print OUT_PREFIX + "Could not resolve crowdDesignator. No crowds found"
            pass

        # Add data from the result of the designator to the list
        if crowdDesgnResult:
            # resolve the data designator
            try:
                crowdData = crowdDataDesignator.resolve()
                entityDataList += [(crowdData)]
                print OUT_PREFIX + "Added " + str(len(crowdData)) + " entities to the list"
            except DesignatorResolvementError:
                print OUT_PREFIX + "Could not resolve dataDesignator"
                pass


        if entityDataList:
            #  iterate through entitities found
            for entityData in entityDataList:
                try:
                    # iterate through faces found in this entity
                    for faceInfo in entityData['perception_result']['face_recognizer']['face']:

                        recognition_label = faceInfo['label']
                        recognition_score = faceInfo['score']
                        face_idx = faceInfo['index']

                        # initialize label as empty string if the recogniton didnt conclude anything
                        if recognition_score == 0:
                            recognition_label = ""
                            print OUT_PREFIX + "Unrecognized person"
                            

                        if entityData['type'] == "crowd":
                            #  get the corresponding location of the face
                            for face_detector_loc in entityData['perception_result']['face_detector']['faces_front']:
                                if face_idx == face_detector_loc['index']:
                                    # get location
                                    face_loc = face_detector_loc
                                    break
                        elif entityData['type'] == "human":
                            face_loc = entityData['perception_result']['face_detector']['faces_front'][0]
                        else:
                            print OUT_PREFIX + bcolors.FAIL + "Uknown entity type. Unable to get face location" + bcolors.ENDC

                        # import ipdb; ipdb.set_trace()

                        #  test if a face in this location is already present in the list
                        sameFace = False
                        for faces in self.facesAnalysedDes.current:
                            # import ipdb; ipdb.set_trace()
                            p1 = (face_loc["map_x"], face_loc["map_y"], face_loc["map_z"])
                            p2 = (faces.point_stamped.point.x,faces.point_stamped.point.y, faces.point_stamped.point.z)

                            if points_distance(p1=p1, p2=p2) < 2.0:
                                sameFace = True

                        if sameFace:
                            print OUT_PREFIX + "Face already present in the list"

                        #  if information is valid, add it to the list of analysed faces
                        if not recognition_label == None and not recognition_score == None and not sameFace:
                            # import ipdb; ipdb.set_trace()
                            print OUT_PREFIX + "Adding this result: '{0}'' (score:{1}) @ ({2},{3},{4})".format(
                                str(recognition_label),
                                str(recognition_score),
                                face_loc["map_x"], face_loc["map_y"], face_loc["map_z"])

                            self.facesAnalysedDes.current += [(FaceAnalysed(point_stamped = msgs.PointStamped(x=face_loc["map_x"], y=face_loc["map_y"], z=face_loc["map_z"], frame_id="/map"),
                                                                            name = recognition_label, 
                                                                            score = recognition_score))]                            
                        else:
                            print OUT_PREFIX + bcolors.WARNING + "Did not add face to the list" + bcolors.ENDC

                except KeyError, ke:
                    print OUT_PREFIX + "KeyError recognition_label/recognition_score: " + str(ke)
                    pass
                except IndexError, ke:
                    print OUT_PREFIX + "IndexError recognition_label/recognition_score: " + str(ke)
                    pass

            print OUT_PREFIX + "Analysed all faces successfully"
            return 'succeded'
        else:
            print OUT_PREFIX + "Could not find anyone in front of the robot"
            return 'failed'


# ----------------------------------------------------------------------------------------------------


# SimpleAction state machine to learn a new face
class LearnPerson(smach.StateMachine):
    # tutorial  for SimpleActionState here http://wiki.ros.org/smach/Tutorials/SimpleActionState
    def __init__(self, robot):
        smach.StateMachine.__init__(self, 
                                    outcomes=['succeded_learning', 'failed_learning'],
                                    input_keys=['personName_in'])
        self.robot = robot
        self.service_name = "/" + robot.robot_name + "/ed/face_recognition/learn_face"

        with self:

            # Callback when a result is received
            def learn_result_cb(userdata, status, result):
                print OUT_PREFIX + bcolors.OKBLUE + "learn_result_cb" + bcolors.ENDC

                print "Received result from the learning service"

                # test the result and parse the message
                if status == actionlib.GoalStatus.SUCCEEDED:
                    if result.result_info == "Learning complete":
                        print "Face learning complete! result: " + result.result_info
                        # self.robot.speech.speak("Learning complete.", block=False)

                        return 'succeeded'
                    else:
                        return 'aborted'
                else:
                    print "Face learning aborted! result: " + result.result_info
                    return 'aborted'

            # Callback when a result is sent
            def learn_goal_cb(userdata, goal):
                print OUT_PREFIX + bcolors.OKBLUE + "goal_result_cb" + bcolors.ENDC
                # import ipdb; ipdb.set_trace()

                self.robot.speech.speak("Please look at me while I learn your face", block=True)

                learn_goal = FaceLearningGoal()
                learn_goal.person_name = userdata.person_name_goal

                print "Goal sent to the learning service, with name '" + learn_goal.person_name + "'"

                return learn_goal

            # Create Simple Action Client
            smach.StateMachine.add( 'LEARN_PERSON',
                                    SimpleActionState(  self.service_name,
                                                        ed_perception.msg.FaceLearningAction,
                                                        result_cb = learn_result_cb,
                                                        goal_cb = learn_goal_cb,            # create a goal inside the callback
                                                        input_keys=['person_name_goal'],
                                                        output_keys=['result_info_out']),
                                                        # goal_slots = ['person_name_goal'],# or create it here directly
                                    transitions={   'succeeded':'succeded_learning',
                                                    'aborted': 'failed_learning',
                                                    'preempted': 'failed_learning'},
                                    remapping={     'person_name_goal':'personName_in'})


# ----------------------------------------------------------------------------------------------------


class GetNextLocation(smach.State):
    """
    From a list of locations to visit, choose the next one and go there
    """
    def __init__(self, robot, locations, nextLocation):
        smach.State.__init__(   self, outcomes=['done', 'visited_all'])

        self.robot = robot
        self.locations = locations
        self.nextLocation = nextLocation

    def execute(self, userdata):
        print OUT_PREFIX + bcolors.OKBLUE + "GetNextLocation" + bcolors.ENDC

        availableLocations = self.locations.resolve()
        
        # if there are locations not visited yet, choose one
        if availableLocations:
            
            print OUT_PREFIX + str(len(availableLocations)) + " locations in the list"
            
            chosenLocation = None
            # TODO: CHOOSE CLOSEST LOCATION
            for loc in availableLocations:

                if loc.visited == False:
                    if loc.attempts < 5:
                        chosenLocation = loc.point_stamped
                        loc.attempts +=1
                        break
                    else:
                        print OUT_PREFIX + 'Tried to visit this location several times and it never worked. Ignoring it'

            if not chosenLocation:
                print OUT_PREFIX + 'All locations are marked as visited'
                return 'visited_all'
            else:
                self.nextLocation.current.setPoint(point_stamped = chosenLocation)
                print OUT_PREFIX + "Next location: " + str(chosenLocation.point)

                return 'done'
            
        # If there are not more loactions to visit then report back to the operator
        else:

            print OUT_PREFIX + "Visited all locations"
            return 'visited_all'
